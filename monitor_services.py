#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import jinja2
from pprint import pprint

compose_file_path = 'generated_compose_file.yml'
prometheus_config_path = 'generated_prometheus_config.yml'

templates = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'), autoescape=None)
compose_file_template = templates.get_template('compose_file_template.yml')
prometheus_config_template = templates.get_template('prometheus_config_template.yml')


def discover_running_containers():
    properties = {'id':'{{.ID}}', 'name':'{{.Names}}', 'image':'{{.Image}}'}
    docker_ps_output = subprocess.check_output(['docker', 'ps', '--format', '\t'.join(properties.values())])
    return [dict(zip(properties.keys(), container_details.split('\t'))) for container_details in docker_ps_output.split('\n')[:-1]]

def generate_template_context(running_containers):
    # {'service_name': {'environment_name': {...container_details...}}} when environment is important
    # {'service_name': [{...container_details...}, ...]} when environment is not important

    exporter_suffix = '-exporter'
    template_context = {}
    for container in running_containers:
        if 'exporter' in container['name']:
            template_context.setdefault('exporter_containers', []).append(container)

        elif 'pg' in container['name']:
            postgres_containers = template_context.setdefault('postgres_containers', {})
            environment = container['name'].split('-')[1]
            container['exporter_name'] = container['name'] + exporter_suffix
            container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
            postgres_containers[environment] = container

        elif 'api' in container['name']:
            # TODO MT currently only handles one container in every environment
            api_containers = template_context.setdefault('isaac_api_containers', {})
            environment = container['name'].split('-')[1]
            container['exporter_name'] = container['name'] + exporter_suffix
            container['prometheus_job_name'] = container['exporter_name'].replace('-', '_')
            api_containers[environment] = container

        elif 'prometheus' in container['name']:
            template_context['prometheus_container'] = container

        else:
            template_context.setdefault('other_containers', []).append(container)

    template_context['prometheus_config_path'] = prometheus_config_path

    return template_context


def generate_compose_file(compose_file_path, template_context):
    with open(compose_file_path, 'w') as file_handle:
        file_handle.write(compose_file_template.render(template_context))


def docker_compose(compose_file_path):
    pass
    """
    docker_compose_exit_code = subprocess.call(['docker-compose', '-f', compose_file_path, 'up', '-d'])
    if docker_compose_exit_code:
        raise Exception('Docker compose exited with a non zero status')
    """


def clean_up_old_containers(template_context):
    pass # TODO MT implement if we want it


def generate_prometheus_config(prometheus_config_path, template_context):
    with open(prometheus_config_path, 'w') as file_handle:
        file_handle.write(prometheus_config_template.render(template_context))


def reload_prometheus_config():
    # TODO MT implement
    # kill -HUP 1234 || curl -X POST http://localhost:9090/-/reload || send_signal(signal.SIGHUP)
    # --web.enable-lifecycle
    pass


if __name__ == '__main__':
    # TODO MT generate only command
    running_containers = discover_running_containers()
    template_context = generate_template_context(running_containers)

    generate_compose_file(compose_file_path, template_context)
    docker_compose(compose_file_path)
    clean_up_old_containers(template_context)

    generate_prometheus_config(prometheus_config_path, template_context)
    reload_prometheus_config()
