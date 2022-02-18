import os
import pathlib
import subprocess

import click
import requests
import urllib3
from ruamel.yaml import YAML

from commands import gyrobot, chat

urllib3.disable_warnings()

usernames = dict()
yaml = YAML()
urllib3.disable_warnings()


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return _read_config(env_var)


def _read_config(env_var):
    if os.environ[env_var].startswith('/'):
        config_file = pathlib.Path(os.environ[env_var])
    else:
        config_file = pathlib.Path('config') / os.environ[env_var]
    with config_file.open() as f:
        actuator_config = yaml.load(f)
    with config_file.with_suffix('.credentials.yml').open() as f:
        credentials = yaml.load(f)
    for env in actuator_config:
        if env in credentials:
            actuator_config[env]['openshift_token'] = credentials[env]
    return actuator_config


@gyrobot.group('actuator')
def actuator():
    pass


class OpenShiftNamespace(click.ParamType):
    name = 'namespace'

    def convert(self, value, param, ctx):
        valid_environments = [e.lower() for e in _actuator_config()]
        if value.lower() not in valid_environments:
            self.fail(f"{value} is not a valid namespace. Try one of those: {', '.join(valid_environments)}", param,
                      ctx)
        return value.lower()


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace())
@click.argument('deployment', type=str)
@click.pass_context
def refresh_actuator(ctx, namespace, deployment):
    namespace_obj = _actuator_config()[namespace]
    server_url = namespace_obj['url']
    ses = requests.session()
    ses.verify = False
    openshift_token = namespace_obj['openshift_token']
    ses.headers['Authorization'] = 'Bearer ' + openshift_token
    all_pods = ses.get(
        server_url + "api/v1/namespaces/omni-dev/pods",
        params={'labelSelector': f'deployment={deployment}'}).json()
    pods_to_refresh = [pod['metadata']['name'] for pod in all_pods]
    for pod_to_refresh in pods_to_refresh:
        port_fwd = subprocess.Popen(['oc', 'port-forward', pod_to_refresh, '9999:8778'])
        refresh_result = requests.get("http://localhost:9999/actuator/configprops")
        print(refresh_result.text)
        port_fwd.terminate()

    chat(ctx).send_file(file_data=all_pods, filename='pods.json')
