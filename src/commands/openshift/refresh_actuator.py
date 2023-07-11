import subprocess
import time

import click
import requests

from commands import gyrobot, chat, logger
from commands.openshift.common import read_config, user_allowed, OpenShiftNamespace, rangify


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return read_config(env_var)


@gyrobot.group('actuator')
def actuator():
    pass


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.pass_context
def refresh_actuator(ctx, namespace, deployments):
    namespace_obj = _actuator_config()[namespace]
    server_url = namespace_obj['url']
    allowed_users = namespace_obj['users']
    if not user_allowed(chat(ctx).user_id, allowed_users):
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
    for deployment in deployments:
        all_pods_raw = ses.get(
            f"{server_url}api/v1/namespaces/{namespace.lower()}/pods",
            params={'labelSelector': f'deployment={deployment}'})
        if not all_pods_raw.ok:
            chat(ctx).send_file(file_data=all_pods_raw.content, filename='error.txt')
            return
        all_pods = all_pods_raw.json()

        login_cmd = subprocess.run(['oc', 'login', f'--token={openshift_token}', f'--server={server_url}'], capture_output=True)
        if login_cmd.returncode != 0:
            chat(ctx).send_text("Error while logging in:\n```" + login_cmd.stderr.decode().strip() + "```", is_error=True)
            return
        pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
        if len(pods_to_refresh) == 0:
            chat(ctx).send_text(f"Couldn't find any pods on {namespace} to refresh for {deployment}", is_error=True)
            return
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
            try:
                pod_env_before = requests.post("http://localhost:9999/actuator/env", proxies={'http': None, 'https': None})
                refresh_result = requests.post("http://localhost:9999/actuator/refresh", proxies={'http': None, 'https': None})
                pod_env_after = requests.post("http://localhost:9999/actuator/env", proxies={'http': None, 'https': None})
                # refresh_result = requests.get("http://localhost:9999/actuator/configprops", proxies={'http': None, 'https': None})
                refresh_actuator_result = refresh_result.json()
                if refresh_actuator_result and all([type(rar) is str for rar in refresh_actuator_result]):
                    # refresh_actuator_result_list = sorted([rar for rar in refresh_actuator_result])
                    refresh_actuator_result_list = rangify(refresh_actuator_result)
                    chat(ctx).send_text('```\n' + '\n'.join(refresh_actuator_result_list) + '\n```\n')
                else:
                    chat(ctx).send_file(
                        file_data=refresh_result.content,
                        filename=f'actuator-refresh-{pod_to_refresh}.json')
            except requests.exceptions.ConnectionError as ex:
                chat(ctx).send_text(f"Error when refreshing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
            port_fwd.terminate()
