import json
import subprocess
import time

import click
import requests
from tabulate import tabulate

from commands import gyrobot, chat, logger
from commands.openshift.common import read_config, OpenShiftNamespace, rangify, check_security


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return read_config(env_var)


@gyrobot.group('actuator')
@click.pass_context
def actuator(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _actuator_config()
    ctx.obj['security_text'] = {'refresh': 'refresh actuator'}


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.pass_context
@check_security
def refresh_actuator(ctx, namespace, deployments):
    namespace_obj = ctx.obj['config'][namespace]
    server_url = namespace_obj['url']
    ses = requests.session()
    if server_url == 'azure':
        tenant_id = namespace_obj['credentials']['tenantId']
        service_principal_id = namespace_obj['credentials']['servicePrincipalId']
        service_principal_key = namespace_obj['credentials']['servicePrincipalKey']

        login_page = ses.post(f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token', data={
            'client_id': service_principal_id,
            'grant_type': 'client_credentials',
            'client_info': 1,
            'client_secret': service_principal_key,
            'scope': 'https://management.core.windows.net//.default'
        })
        ses.headers['Authorization'] = 'Bearer ' + login_page.json()['access_token']
        subscriptions_page = ses.get("https://management.azure.com/subscriptions?api-version=2019-11-01")
        chat(ctx).send_file(subscriptions_page.content, filename='subscriptions.json')
        return
    else:
        openshift_token = namespace_obj['credentials']
        ses.headers['Authorization'] = 'Bearer ' + openshift_token

    for deployment in deployments:
        all_pods = _get_pods(ctx, namespace, server_url, ses, deployment)
        if not all_pods: return

        login_cmd = subprocess.run(
            ['oc', 'login', f'--token={openshift_token}', f'--server={server_url}'],
            capture_output=True)
        if login_cmd.returncode != 0:
            stderr_output = login_cmd.stderr.decode().strip()
            chat(ctx).send_text(f"Error while logging in:\n```{stderr_output}```", is_error=True)
            return
        pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
        if len(pods_to_refresh) == 0:
            chat(ctx).send_text(f"Couldn't find any pods on {namespace} to refresh for {deployment}", is_error=True)
            return
        for pod_to_refresh in pods_to_refresh:
            port_fwd = _start_port_forward(ctx, pod_to_refresh)
            try:
                empty_proxies = {'http': None, 'https': None}
                pod_env_before = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies)
                refresh_result = requests.post("http://localhost:9999/actuator/refresh", proxies=empty_proxies)
                pod_env_after = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies)
                _send_results(ctx, pod_to_refresh, pod_env_before, refresh_result, pod_env_after)
            except requests.exceptions.ConnectionError as ex:
                chat(ctx).send_text(f"Error when refreshing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
            port_fwd.terminate()


def _start_port_forward(ctx, pod_to_refresh):
    port_fwd = subprocess.Popen(
        ['oc', 'port-forward', pod_to_refresh, '9999:8778'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
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
    return port_fwd


def _get_pods(ctx, namespace, server_url, ses, deployment):
    all_pods_raw = ses.get(
        f"{server_url}api/v1/namespaces/{namespace.lower()}/pods",
        params={'labelSelector': f'deployment={deployment}'})
    if not all_pods_raw.ok:
        chat(ctx).send_file(file_data=all_pods_raw.content, filename='error.txt')
        return None
    all_pods = all_pods_raw.json()
    return all_pods


def _send_results(ctx, pod_to_refresh, pod_env_before, refresh_result, pod_env_after):
    refresh_actuator_result = refresh_result.json()
    if type(refresh_actuator_result) is list:
        value_types = [isinstance(rar, str) for rar in refresh_actuator_result]
        all_values_are_strings = all(value_types)
    else:
        all_values_are_strings = False
    if refresh_result.ok and refresh_actuator_result and all_values_are_strings:
        refresh_actuator_result_list = rangify(refresh_actuator_result, consolidate=False)
        # chat(ctx).send_text('```\n' + '\n'.join(refresh_actuator_result_list) + '\n```\n')
        env_before = json.loads(pod_env_before.content)
        env_after = json.loads(pod_env_after.content)
        values_before = {}
        values_after = {}
        for c in refresh_actuator_result_list:
            for ps in env_before['propertySources']:
                if c in ps['properties']:
                    values_before[c] = ps['properties'][c]
            for ps in env_after['propertySources']:
                if c in ps['properties']:
                    values_after[c] = ps['properties'][c]
        full_changes = [{
            'variable': c,
            'before': values_before.get(c, {'value': None})['value'],
            'after_value': values_after.get(c, {'value': None})['value'],
            'after_origin': values_after.get(c, {'origin': None}).get('origin')}
            for c in refresh_actuator_result_list]
        result_table = tabulate(full_changes, headers='keys', tablefmt='pipe')
        chat(ctx).send_text(f"Changes for pod {pod_to_refresh}:\n```{result_table}\n```")
    else:
        chat(ctx).send_file(
            file_data=pod_env_before.content,
            filename=f'pod_env_before-{pod_to_refresh}.json')
        chat(ctx).send_file(
            file_data=refresh_result.content,
            filename=f'actuator-refresh-{pod_to_refresh}.json')
        chat(ctx).send_file(
            file_data=pod_env_after.content,
            filename=f'pod_env_after-{pod_to_refresh}.json')
