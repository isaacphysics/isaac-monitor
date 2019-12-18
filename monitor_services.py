#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import functools
import jinja2
import requests
import subprocess
import sys

no_prompt = False

def report_execution(function):
    @functools.wraps(function)
    def decorated_function(*args, **kwargs):
        if no_prompt:
            print('[{}]'.format(function.__name__.upper()))
        elif input('\nAbout to {}, continue (y/n)?\n>'.format(function.__name__.replace('_', ' '))).lower() != 'y':
            print('Aborting execution')
            sys.exit(1)
        return function(*args, **kwargs)
    return decorated_function

def discover_running_containers():
    properties = {'id':'{{.ID}}', 'name':'{{.Names}}', 'image':'{{.Image}}'}
    docker_ps_output = str(subprocess.check_output(['docker', 'ps', '--format', '\t'.join(properties.values())]))
    running_containers = []
    for container_details in docker_ps_output.split('\\n')[:-1]:
        running_containers.append(dict(zip(properties.keys(), container_details.split('\\t'))))
    print('Found {} running containers:\n{}'.format(len(running_containers), sorted(container['name'] for container in running_containers)))
    return running_containers

def generate_template_context(running_containers, target_environments):
    exporter_suffix = '-exporter'

    template_context = {}
    for container in sorted(running_containers, key=lambda c: c['name']):
        if 'exporter' in container['name']:
            template_context.setdefault('exporter_containers', []).append(container)
        elif 'api' in container['name']:
            subject, container_type, environment, tag = container['name'].split('-')
            if not target_environments or environment in target_environments:
                container['exporter_name'] = container['name'] # container exposes a port
                container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
                api_containers = template_context.setdefault('isaac_api_containers', {})
                subject_api_containers = api_containers.setdefault(subject, {})
                environment_api_containers = subject_api_containers.setdefault(environment, {})
                environment_api_containers[tag] = container
        elif 'pg' in container['name']:
            subject, container_type, environment = container['name'].split('-')
            if not target_environments or environment in target_environments:
                container['exporter_name'] = container['name'] + exporter_suffix
                container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
                postgres_containers = template_context.setdefault('postgres_containers', {})
                subject_containers = postgres_containers.setdefault(subject, {})
                subject_containers[environment] = container
        else:
            template_context.setdefault('other_containers', []).append(container)

    template_context['prometheus_config_path'] = prometheus_config_path

    return template_context

@report_execution
def generate_compose_file(compose_file_path, template_context, **kwargs):
    with open(compose_file_path, 'w') as file_handle:
        file_handle.write(compose_file_template.render(template_context))
        print("Compose file generated and written to " + compose_file_path)

@report_execution
def docker_compose(compose_file_path, compose_args=['up', '-d'], **kwargs):
    docker_compose_exit_code = subprocess.call(['docker-compose', '-f', compose_file_path] + compose_args)
    if docker_compose_exit_code:
        raise Exception('Docker compose exited with a non zero status: {}'.format(docker_compose_exit_code))

@report_execution
def clean_up_old_containers(template_context, **kwargs):
    print('NOTE: Clean up old containers is not implemented.')
    print('Skipping...')

@report_execution
def generate_prometheus_config(prometheus_config_path, template_context, **kwargs):
    with open(prometheus_config_path, 'w') as file_handle:
        file_handle.write(prometheus_config_template.render(template_context))
        print('Prometheus config generated and written to ' + prometheus_config_path)

@report_execution
def reload_prometheus_config(**kwargs):
    docker_reload_exit_code = subprocess.call(['docker', 'kill', '--signal=HUP', 'prometheus'])
    if docker_reload_exit_code:
        raise Exception('Error: The reload request to Prometheus was not successfull: {}'.format(docker_reload_exit_code))

def parse_command_line_arguments(all_actions):
    parser = argparse.ArgumentParser(description='Automate monitoring containers and prometheus targets.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='run all actions: [{}]'.format(', '.join(action.__name__ for action in all_actions)))
    group.add_argument('--generate', action='store_true', help='generate compose and prometheus files only')
    group.add_argument('--compose', nargs='*', help='runs docker-compose with the trailing arguments on the generated compose file')
    group.add_argument('--clean', action='store_true', help='clean-up old monitor containers')
    group.add_argument('--reload', action='store_true', help='reload prometheus config only')
    parser.add_argument('--target-environments', '--environments', '-e', nargs='+', choices=['test', 'dev', 'staging', 'live'], default=['live'], help='limit monitoring to specific environments')
    parser.add_argument('--no-prompt', action="store_true", help='disable action prompts')
    return parser.parse_args()


if __name__ == '__main__':
    templates = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=None)
    compose_file_template = templates.get_template('compose_file_template.yml')
    prometheus_config_template = templates.get_template('prometheus_config_template.yml')

    compose_file_path = 'generated_compose_file.yml'
    prometheus_config_path = 'generated_prometheus_config.yml'

    all_actions = [generate_compose_file, docker_compose, clean_up_old_containers, generate_prometheus_config, reload_prometheus_config]
    cli_args = parse_command_line_arguments(all_actions)
    no_prompt = cli_args.no_prompt

    if not no_prompt and not sys.stdout.isatty():
        print('\nError: Must run this method with a tty unless you specify --no-prompt. If you\'re using windows try:')
        print('winpty {}'.format(' '.join(sys.argv)))
        sys.exit(1)

    running_containers = discover_running_containers()
    template_context = generate_template_context(running_containers, cli_args.target_environments)
    action_args = {'template_context': template_context, 'compose_file_path': compose_file_path, 'prometheus_config_path': prometheus_config_path}

    actions = []
    if cli_args.all:
        actions = all_actions
    if cli_args.generate:
        actions = [generate_compose_file, generate_prometheus_config]
    if cli_args.reload:
        actions = [reload_prometheus_config]
    if cli_args.clean:
        actions = [clean_up_old_containers]
    if cli_args.compose:
        action_args['compose_args'] = cli_args.compose
        actions = [docker_compose]

    for action in actions:
        action(**action_args)

