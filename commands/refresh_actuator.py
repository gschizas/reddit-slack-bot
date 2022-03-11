import os
import pathlib
import subprocess
import time

import click
import requests
from ruamel.yaml import YAML

from commands import gyrobot, chat, logger

yaml = YAML()
all_users = []
all_users_last_update = 0


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return _read_config(env_var)


def _read_config(env_var):
    if os.environ[env_var].startswith('/'):
        config_file = pathlib.Path(os.environ[env_var])
    else:
        config_file = pathlib.Path('config') / os.environ[env_var]
    with config_file.open(encoding='utf8') as f:
        actuator_config = yaml.load(f)
    with config_file.with_suffix('.credentials.yml').open(encoding='utf8') as f:
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


def _user_allowed(slack_user_id, allowed_users):
    global all_users, all_users_last_update
    if '*' in allowed_users:
        return True
    if slack_user_id in allowed_users:
        return True
    allowed_groups = [g[1:] for g in allowed_users if g.startswith('@')]

    all_users_file = pathlib.Path('data/crowd_users.yml')
    if all_users is None or all_users_file.stat().st_mtime != all_users_last_update:
        with all_users_file.open(encoding='utf8') as f:
            all_users = yaml.load(f)
        all_users_last_update = all_users_file.stat().st_mtime
    crowd_users = list(filter(lambda x: x.get('$slack-user-id') == slack_user_id, all_users))
    if len(crowd_users) != 1:
        return False
    crowd_user = crowd_users[0]
    user_groups = crowd_user['groups']
    if set(allowed_groups).intersection(user_groups):
        return True
    return False


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace())
@click.argument('deployment', type=str)
@click.pass_context
def refresh_actuator(ctx, namespace, deployment):
    namespace_obj = _actuator_config()[namespace]
    server_url = namespace_obj['url']
    allowed_users = namespace_obj['users']
    if not _user_allowed(chat(ctx).user_id, allowed_users):
        chat(ctx).send_text(f"You don't have permission to refresh actuator.", is_error=True)
        return
    allowed_channels = namespace_obj['channels']
    channel_name = chat(ctx).channel_name
    if channel_name not in allowed_channels:
        chat(ctx).send_text(f"Refresh actuator commands are not allowed in {channel_name}", is_error=True)
        return
    ses = requests.session()
    openshift_token = namespace_obj['openshift_token']
    ses.headers['Authorization'] = 'Bearer ' + openshift_token
    all_pods_raw = ses.get(
        server_url + "api/v1/namespaces/omni-dev/pods",
        params={'labelSelector': f'deployment={deployment}'})
    all_pods = all_pods_raw.json()

    login_cmd = subprocess.run(['oc', 'login', f'--token={openshift_token}', f'--server={server_url}'], capture_output=True)
    if login_cmd.returncode != 0:
        chat(ctx).send_text("Error while logging in:\n```" + login_cmd.stderr.decode().strip() + "```", is_error=True)
        return
    pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
    for pod_to_refresh in pods_to_refresh:
        port_fwd = subprocess.Popen(['oc', 'port-forward', pod_to_refresh, '9999:8778'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while True:
            if port_fwd.poll() is not None:
                if port_fwd.returncode != 0:
                    port_fwd.stderr.flush()
                    err_line = port_fwd.stderr.readline()
                    logger(ctx).debug(err_line.decode().strip())
                break
            out_line = port_fwd.stdout.readline()
            logger(ctx).debug(out_line.decode().strip())
            if out_line == b'Forwarding from 127.0.0.1:9999 -> 8778\n':
                logger(ctx).debug("Port forward Listening ok")
                break
            time.sleep(0.2)
        refresh_result = requests.post("http://localhost:9999/actuator/refresh", proxies={'http': None, 'https': None})
        # refresh_result = requests.get("http://localhost:9999/actuator/configprops", proxies={'http': None, 'https': None})
        chat(ctx).send_file(file_data=refresh_result.content, filename=f'actuator-refresh-{pod_to_refresh}.json')
        port_fwd.terminate()
