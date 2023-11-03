import base64
import io
import json
import subprocess
import time

import click
import requests
from ruamel.yaml import YAML

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.common import read_config, OpenShiftNamespace, rangify, check_security, env_config

KUBERNETES_SERVICE_AAD_SERVER_GUID = '6dae42f8-4368-4678-94ff-3960e28e3630'
yaml = YAML()


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return read_config(env_var)


@gyrobot.group('actuator')
@click.pass_context
def actuator(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _actuator_config()
    ctx.obj['security_text'] = {'refresh': 'refresh actuator', 'view': 'view actuator variables', 'pods': 'view pods'}


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.pass_context
@check_security
def refresh_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str]):
    project_name, server_url, ses_k8s = _connect_openshift(ctx, namespace)

    for deployment in deployments:
        all_pods = _get_pods(ctx, project_name, server_url, ses_k8s, deployment)
        if not all_pods: continue

        pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
        if len(pods_to_refresh) == 0:
            ctx.chat.send_text(f"Couldn't find any pods on {namespace} to view for {deployment}", is_error=True)
        for pod_to_refresh in pods_to_refresh:
            port_fwd = _start_port_forward(ctx, pod_to_refresh)
            try:
                empty_proxies = {'http': None, 'https': None}
                pod_env_before = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies, timeout=30)
                refresh_result = requests.post("http://localhost:9999/actuator/refresh", proxies=empty_proxies, timeout=30)
                pod_env_after = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies, timeout=30)
                _send_results(ctx, pod_to_refresh, pod_env_before, refresh_result, pod_env_after)
            except requests.exceptions.ConnectionError as ex:
                ctx.chat.send_text(f"Error when refreshing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
            port_fwd.terminate()


def _connect_openshift(ctx: ExtendedContext, namespace):
    namespace_obj = env_config(ctx, namespace)
    server_url = namespace_obj['url']
    ses_main = requests.session()
    if server_url == 'azure':
        tenant_id = namespace_obj['credentials']['tenantId']
        service_principal_id = namespace_obj['credentials']['servicePrincipalId']
        service_principal_key = namespace_obj['credentials']['servicePrincipalKey']
        resource_group = namespace_obj['azure_resource_group']
        cluster_name = namespace_obj['azure_cluster_name']
        project_name = namespace_obj['project_name']

        login_page = ses_main.post(f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token', data={
            'client_id': service_principal_id,
            'grant_type': 'client_credentials',
            'client_info': 1,
            'client_secret': service_principal_key,
            'scope': 'https://management.core.windows.net/.default'
        })
        azure_token = login_page.json()['access_token']
        ses_main.headers['Authorization'] = 'Bearer ' + azure_token
        subscriptions_page = ses_main.get("https://management.azure.com/subscriptions?api-version=2019-11-01")
        subscription_id = subscriptions_page.json()['value'][0]['subscriptionId']

        ctx.chat.send_file(subscriptions_page.content, filename='subscriptions.json')

        aks_credentials_page = ses_main.post(
            (f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups"
             f"/{resource_group}/providers/Microsoft.ContainerService/managedClusters"
             f"/{cluster_name}/listClusterUserCredential?api-version=2022-03-01"))
        aks_credentials = aks_credentials_page.json()
        aks_value_raw = list(filter(lambda x: x['name'] == 'clusterUser', aks_credentials['kubeconfigs']))[0]['value']
        with io.BytesIO(base64.b64decode(aks_value_raw)) as f:
            aks_value = yaml.load(f)
        cluster_url = list(filter(lambda x: x['name'] == cluster_name, aks_value['clusters']))[0]['cluster']['server']
        server_url = cluster_url + '/'

        kubernetes_token_raw = ses_main.post(
            f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token',
            data={
                'client_id': service_principal_id,
                'grant_type': 'client_credentials',
                'client_info': 1,
                'client_secret': service_principal_key,
                'scope': f'{KUBERNETES_SERVICE_AAD_SERVER_GUID}/.default'
            })
        kubernetes_token = kubernetes_token_raw.json()

        kubelogin_proc = subprocess.run(
            ['kubelogin', '-v', '4', 'convert-kubeconfig', '-l,' 'azurecli'],
            capture_output=True)

        ctx.logger.debug('Kubelogin Result: ' + repr(kubelogin_proc))

        ses_k8s = requests.session()
        ses_k8s.headers['Authorization'] = 'Bearer ' + kubernetes_token['access_token']
    else:
        openshift_token = namespace_obj['credentials']
        ses_main.headers['Authorization'] = 'Bearer ' + openshift_token
        login_cmd = subprocess.run(
            ['oc', 'login', f'--token={openshift_token}', f'--server={server_url}'],
            capture_output=True)
        if login_cmd.returncode != 0:
            stderr_output = login_cmd.stderr.decode().strip()
            error_text = f"Error while logging in:\n```{stderr_output}```"
            ctx.chat.send_text(error_text, is_error=True)
            raise RuntimeError("Error while logging in", stderr_output)
        ses_k8s = ses_main
        project_name = namespace
    return project_name, server_url, ses_k8s


@actuator.command('view')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def view_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool):
    project_name, server_url, ses_k8s = _connect_openshift(ctx, namespace)

    for deployment in deployments:
        all_pods = _get_pods(ctx, project_name, server_url, ses_k8s, deployment)
        if not all_pods: continue

        pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
        if len(pods_to_refresh) == 0:
            ctx.chat.send_text(f"Couldn't find any pods on {namespace} to view for {deployment}", is_error=True)
        for pod_to_refresh in pods_to_refresh:
            port_fwd = _start_port_forward(ctx, pod_to_refresh)
            try:
                empty_proxies = {'http': None, 'https': None}
                pod_env = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies, timeout=30)
                _send_env_results(ctx, pod_to_refresh, pod_env, excel)
            except requests.exceptions.ConnectionError as ex:
                ctx.chat.send_text(f"Error when refreshing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
            port_fwd.terminate()


@actuator.command('pods')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.pass_context
@check_security
def pods(ctx: ExtendedContext, namespace: str):
    project_name, server_url, ses_k8s = _connect_openshift(ctx, namespace)

    all_pods_raw = ses_k8s.get(
        f"{server_url}api/v1/namespaces/{namespace.lower()}/pods")
    if not all_pods_raw.ok:
        ctx.chat.send_file(file_data=all_pods_raw.content, filename='error.txt')
        return None
    #ctx.chat.send_file(file_data=all_pods_raw.content, filename=f"{namespace}-pods.json")
    fields = ['deployment', 'name', 'podIP']
    pods = [dict(zip(fields, [
        pod['metadata']['labels'].get('deployment'),
        pod['metadata']['name'],
        pod['status']['podIP']])) for pod in all_pods_raw.json()['items']]
    ctx.chat.send_table(title=f"pods-{namespace}", table=pods)


def _start_port_forward(ctx: ExtendedContext, pod_to_refresh: str):
    ctx.logger.debug(f"Starting port forward for {pod_to_refresh}")
    port_fwd = subprocess.Popen(
        ['oc', 'port-forward', pod_to_refresh, '9999:8778'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    process_started_at = time.time()
    while True:
        if process_started_at + 30 < time.time():
            ctx.logger.error("Port forward timed out")
            raise RuntimeError("Port forward timed out")
        if port_fwd.poll() is not None:
            if port_fwd.returncode != 0:
                port_fwd.stderr.flush()
                err_line = port_fwd.stderr.readline()
                ctx.logger.error(err_line.decode().strip())
            break
        out_line = port_fwd.stdout.readline()
        err_line = port_fwd.stderr.readline()
        ctx.logger.debug(out_line.decode().strip())
        if err_line:
            ctx.logger.error(err_line.decode().strip())
        if out_line == b'Forwarding from 127.0.0.1:9999 -> 8778\n':
            ctx.logger.debug("Port forward Listening ok")
            break
        time.sleep(0.2)
    return port_fwd


def _get_pods(ctx: ExtendedContext, namespace: str, server_url: str, ses: requests.Session, deployment: str):
    all_pods_raw = ses.get(
        f"{server_url}api/v1/namespaces/{namespace.lower()}/pods",
        params={'labelSelector': f'deployment={deployment}'})
    if not all_pods_raw.ok:
        ctx.chat.send_file(file_data=all_pods_raw.content, filename='error.txt')
        return None
    all_pods = all_pods_raw.json()
    return all_pods


def _send_results(ctx: ExtendedContext,
                  pod_to_refresh: str,
                  pod_env_before: requests.Response,
                  refresh_result: requests.Response,
                  pod_env_after: requests.Response):
    def _environment_changes_table(pod_env_before_raw, pod_env_after_raw, result_list):
        env_before = json.loads(pod_env_before_raw.content)
        env_after = json.loads(pod_env_after_raw.content)
        values_before = {}
        values_after = {}
        for c in result_list:
            property_names = ('bootstrapProperties', 'propertySources')
            if not any([p in env_before for p in property_names]) or not any([p in env_after for p in property_names]):
                ctx.chat.send_text("Could not find property sources in environment", is_error=True)
                ctx.chat.send_file(pod_env_before_raw.content, filename='EnvBefore.json')
                ctx.chat.send_file(pod_env_after_raw.content, filename='EnvAfter.json')
                return []
            for ps in env_before.get('propertySources', env_before.get('bootstrapProperties', [])):
                if c in ps['properties']:
                    values_before[c] = ps['properties'][c]
            for ps in env_after.get('propertySources', env_after.get('bootstrapProperties', [])):
                if c in ps['properties']:
                    values_after[c] = ps['properties'][c]
        return [{
            'variable': c,
            'before': values_before.get(c, {'value': None})['value'],
            'after_value': values_after.get(c, {'value': None})['value'],
            'after_origin': values_after.get(c, {'origin': None}).get('origin')}
            for c in result_list]

    refresh_actuator_result = refresh_result.json()
    if type(refresh_actuator_result) is list:
        value_types = [isinstance(rar, str) for rar in refresh_actuator_result]
        all_values_are_strings = all(value_types)
    else:
        all_values_are_strings = False
    if refresh_result.ok and refresh_actuator_result and all_values_are_strings:
        refresh_actuator_result_list = rangify(refresh_actuator_result, consolidate=False)
        # ctx.chat.send_text('```\n' + '\n'.join(result_list) + '\n```\n')
        if full_changes := _environment_changes_table(pod_env_before, pod_env_after, refresh_actuator_result_list):
            ctx.chat.send_table(f"Changes for pod {pod_to_refresh}", full_changes)
    else:
        ctx.chat.send_file(
            file_data=pod_env_before.content,
            filename=f'pod_env_before_raw-{pod_to_refresh}.json')
        ctx.chat.send_file(
            file_data=refresh_result.content,
            filename=f'actuator-refresh-{pod_to_refresh}.json')
        ctx.chat.send_file(
            file_data=pod_env_after.content,
            filename=f'pod_env_after_raw-{pod_to_refresh}.json')


def _send_env_results(ctx: ExtendedContext, pod_to_refresh, pod_env, excel: bool):
    def _environment_table(pod_env_raw):
        env_current = json.loads(pod_env_raw.content)
        property_names = ('bootstrapProperties', 'propertySources')
        if not any([p in env_current for p in property_names]):
            ctx.chat.send_text("Could not find property sources in environment", is_error=True)
            ctx.chat.send_file(pod_env_raw.content, filename='EnvCurrent.json')
            return []
        else:
            all_values = []
            for ps in env_current.get('propertySources', env_current.get('bootstrapProperties', [])):
                for prop_name, prop_value in sorted(ps['properties'].items()):
                    all_values.append({
                        'sourceName': ps['name'],
                        'name': prop_name,
                        'value': prop_value['value'],
                        'origin': prop_value.get('origin')})
            return all_values

    if full_env := _environment_table(pod_env):
        ctx.chat.send_table(f"Changes for pod {pod_to_refresh}", full_env, send_as_excel=excel)
