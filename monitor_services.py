#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import jinja2
import requests
import subprocess
from pprint import pprint

compose_file_path = 'generated_compose_file.yml'
prometheus_config_path = 'generated_prometheus_config.yml'
verbose = False

templates = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=None)
compose_file_template = templates.get_template('compose_file_template.yml')
prometheus_config_template = templates.get_template('prometheus_config_template.yml')


def discover_running_containers():
    properties = {'id':'{{.ID}}', 'name':'{{.Names}}', 'image':'{{.Image}}'}
    docker_ps_output = subprocess.check_output(['docker', 'ps', '--format', '\t'.join(properties.values())])
    return [dict(zip(properties.keys(), container_details.split('\t'))) for container_details in docker_ps_output.split('\n')[:-1]]


def generate_template_context(running_containers, target_environments):
    # {'service_name': {'environment_name': {...container_details...}}} when environment is important
    # {'service_name': [{...container_details...}, ...]} when environment is not important
    exporter_suffix = '-exporter'

    template_context = {}
    for container in running_containers:
        if 'exporter' in container['name']:
            template_context.setdefault('exporter_containers', []).append(container)
        elif 'pg' in container['name']:
            environment = container['name'].split('-')[1]
            if not target_environments or environment in target_environments:
                postgres_containers = template_context.setdefault('postgres_containers', {})
                container['exporter_name'] = container['name'] + exporter_suffix
                container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
                postgres_containers[environment] = container
        elif 'api' in container['name']:
            # TODO MT currently only handles one container in every environment
            environment = container['name'].split('-')[1]
            if not target_environments or environment in target_environments:
                api_containers = template_context.setdefault('isaac_api_containers', {})
                container['exporter_name'] = container['name'] # container exposes a port
                container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
                api_containers[environment] = container
        else:
            template_context.setdefault('other_containers', []).append(container)

    template_context['prometheus_config_path'] = prometheus_config_path

    return template_context


def generate_compose_file(compose_file_path, template_context, **kwargs):
    with open(compose_file_path, 'w') as file_handle:
        file_handle.write(compose_file_template.render(template_context))


def docker_compose(compose_file_path, compose_args=['up', '-d'], **kwargs):
    docker_compose_exit_code = subprocess.call(['docker-compose', '-f', compose_file_path] + compose_args)
    if docker_compose_exit_code:
        raise Exception('Docker compose exited with a non zero status')


def clean_up_old_containers(template_context, **kwargs):
    pass # TODO MT implement if we want it


def generate_prometheus_config(prometheus_config_path, template_context, **kwargs):
    with open(prometheus_config_path, 'w') as file_handle:
        file_handle.write(prometheus_config_template.render(template_context))


def reload_prometheus_config(**kwargs):
    response = requests.post('http://localhost:9090/-/reload')
    if not response.ok:
        raise Exception('Error: The reload request to Prometheus was not successfull ({} : {})'.format(response.status_code, response.reason))


def parse_command_line_arguments():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--target-environments', '--environments', '-e', nargs='+', choices=['test', 'dev', 'staging', 'live'], help='limit monitoring to specific environments')
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--generate', action='store_true', help='generate compose and prometheus files only')
    group.add_argument('--reload', action='store_true', help='reload prometheus config only')
    group.add_argument('--clean', action='store_true', help='clean-up old monitor containers')
    group.add_argument('--compose', nargs='*', help='passes following arguments through to docker-compose')
    parser.add_argument('--verbose', '-v', action='store_true', help='verbose output')
    return parser.parse_args()


if __name__ == '__main__':
    cli_args = parse_command_line_arguments()
    if cli_args.verbose:
        print("TODO add useful info for verbose output!")

    running_containers = discover_running_containers()
    template_context = generate_template_context(running_containers, cli_args.target_environments)
    action_args = {'template_context': template_context, 'compose_file_path': compose_file_path, 'prometheus_config_path': prometheus_config_path}

    actions = [generate_compose_file, docker_compose, clean_up_old_containers, generate_prometheus_config, reload_prometheus_config]
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
        print('-- {} --'.format(action.func_name.upper()))
        action(**action_args)

