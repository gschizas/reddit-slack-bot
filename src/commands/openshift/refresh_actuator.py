import json
from typing import Callable

import click
import kubernetes.client
import requests
from cryptography import x509

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.api import KubernetesConnection
from commands.openshift.common import read_config, OpenShiftNamespace, rangify, check_security


def _actuator_config():
    env_var = 'OPENSHIFT_ACTUATOR_REFRESH'
    return read_config(env_var)


@gyrobot.group('actuator')
@click.pass_context
def actuator(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _actuator_config()
    ctx.obj['security_text'] = {
        'refresh': 'refresh actuator',
        'health': 'view actuator health',
        'view': 'view actuator variables',
        'pods': 'view pods'}


@actuator.command('refresh')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def refresh_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool):
    def refresh_action(conn, pod_results, pod_to_refresh):
        empty_proxies = {'http': None, 'https': None}
        response_before = requests.get(
            url=f'http://{pod_to_refresh}.pod.{conn.project_name}.kubernetes:8778/actuator/env',
            proxies=empty_proxies, timeout=30)
        refresh_result = requests.post(
            url=f'http://{pod_to_refresh}.pod.{conn.project_name}.kubernetes:8778/actuator/refresh',
            proxies=empty_proxies, timeout=30)
        response_after = requests.get(
            url=f'http://{pod_to_refresh}.pod.{conn.project_name}.kubernetes:8778/actuator/env',
            proxies=empty_proxies, timeout=30)
        pod_results[pod_to_refresh + ' - before'] = _environment_table(response_before)
        pod_results[pod_to_refresh + ' - change'] = _environment_changes_table(
            response_before, response_after, refresh_result)
        pod_results[pod_to_refresh + ' - after'] = _environment_table(response_after)

    action_names = ('refresh', 'Refreshed')

    _actuator_action(ctx, namespace, deployments, excel, action_names, refresh_action)


@actuator.command('view')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def view_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool):
    def view_action(conn, pod_results, pod_to_refresh):
        response = requests.get(
            url=f'http://{pod_to_refresh}.pod.{conn.project_name}.kubernetes:8778/actuator/env',
            proxies={'http': None, 'https': None},
            timeout=30)
        pod_results[pod_to_refresh] = _environment_table(response)

    action_names = ('view', 'Viewed')

    _actuator_action(ctx, namespace, deployments, excel, action_names, view_action)


@actuator.command('health')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def health_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool):
    def health_action(conn, pod_results, pod):
        response = requests.get(
            url=f'http://{pod}.pod.{conn.project_name}.kubernetes:8778/actuator/health',
            proxies={'http': None, 'https': None},
            timeout=30)
        health_raw = response.json()
        health_table = []
        for key, value in health_raw['components'].items():
            if key == 'diskSpace':
                disk_space_raw = value['details']['free'] / value['details']['total']
                disk_space = f"{disk_space_raw:3.2%}"
            else:
                disk_space = ''
            health_table.append(
                {'Name': key,
                 'Status': value.get('status'),
                 'DiskSpace': disk_space,
                 'Version': value.get('details', {}).get('version')})
        pod_results[pod] = health_table

    action_names = ('view health', 'Viewed health')

    _actuator_action(ctx, namespace, deployments, excel, action_names, health_action)


def _actuator_action(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool,
                     action_names: tuple[str, str], action: Callable):
    with KubernetesConnection(ctx, namespace) as conn:
        for deployment in deployments:
            label_selector = f'deployment={deployment}'
            all_pods: kubernetes.client.V1PodList = conn.core_v1_api.list_namespaced_pod(namespace=conn.project_name,
                                                                                         label_selector=label_selector)
            pods_to_refresh = [pod.metadata.name for pod in all_pods.items]
            if len(pods_to_refresh) == 0:
                ctx.chat.send_text(
                    f"Couldn't find any pods on {conn.project_name} to {action_names[0]} for {deployment}",
                    is_error=True)
                continue

            pods_actioned_successful = 0
            pod_results = {}
            for pod_to_refresh in pods_to_refresh:
                with conn.port_forward():
                    try:
                        action(conn, pod_results, pod_to_refresh)
                        pods_actioned_successful += 1
                    except requests.exceptions.ConnectionError as ex:
                        pod_results[pod_to_refresh] = [{'State': 'Error', 'Message': repr(ex)}]
            ctx.chat.send_text(
                f"{action_names[1]} {pods_actioned_successful}/{len(pods_to_refresh)} pods for {deployment}")
            ctx.chat.send_tables('PodStatus', pod_results, excel)


@actuator.command('pods')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('pod_name', type=str, required=False)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def pods(ctx: ExtendedContext, namespace: str, pod_name: str = None, excel: bool = False):
    with KubernetesConnection(ctx, namespace) as conn:
        label_selector = f'deployment={pod_name}' if pod_name else None
        all_pods: kubernetes.client.V1PodList = conn.core_v1_api.list_namespaced_pod(namespace=conn.project_name,
                                                                                     label_selector=label_selector)

        fields = ["Deployment", "Name", "Ready", "Status", "Restarts", "Host IP", "Pod IP"]
        pods_list = [dict(zip(fields, [
            pod.metadata.labels.get('deployment'),
            pod.metadata.name,
            all([cs.ready for cs in pod.status.container_statuses]),
            pod.status.phase,
            sum([cs.restart_count for cs in pod.status.container_statuses]),
            pod.status.host_ip,
            pod.status.pod_ip])) for pod in all_pods.items]
        ctx.chat.send_table(title=f"pods-{conn.project_name}", table=pods_list, send_as_excel=excel)


def _environment_table(pod_env_raw):
    env_current = json.loads(pod_env_raw.content)

    if 'propertySources' in env_current:  # Spring Boot v2+
        property_sources = env_current.get('propertySources')
        bootstrap_properties = [prop for prop in property_sources if prop['name'].startswith('bootstrapProperties')]
        if not bootstrap_properties:
            return [
                {'Status': 'Error',
                 'Message': "Could not find property sources in environment (maybe spring boot 2.7?)"}]
        property_root = {}
        for bootstrap_property in bootstrap_properties:
            if bootstrap_property['properties'] == {}:
                continue
            common_keys = list(set(bootstrap_property['properties'].keys()) & set(property_root.keys()))
            assert not common_keys
            property_root.update(bootstrap_property['properties'])
        complex_properties = True
    elif 'bootstrapProperties' in env_current:  # Spring Boot v1.5, only one dictionary, get to it directly
        property_root = env_current.get('bootstrapProperties')
        complex_properties = False
    else:
        return [{'Status': 'Error', 'Message': "Could not find property sources in environment"}]

    all_values = []
    for prop_name, prop_value in sorted(property_root.items()):
        if complex_properties:
            real_value = prop_value['value']
            prop_origin = prop_value.get('origin')
        else:
            real_value = prop_value
            prop_origin = None

        if type(real_value) is str and real_value.startswith('-----BEGIN CERTIFICATE-----\n'):
            cert = x509.load_pem_x509_certificate(real_value.encode())
            real_value = (f"Certificate ({cert.serial_number}) "
                          f"valid {cert.not_valid_before_utc} — {cert.not_valid_after_utc} (UTC)")

        all_values.append({
            'name': prop_name,
            'value': real_value,
            'origin': prop_origin})
    return all_values


def _environment_changes_table(pod_env_before_raw, pod_env_after_raw, result_list):
    env_before = json.loads(pod_env_before_raw.content)
    env_after = json.loads(pod_env_after_raw.content)
    values_before = {}
    values_after = {}
    for c in result_list:
        property_names = ('bootstrapProperties', 'propertySources')
        if not any([p in env_before for p in property_names]) or not any([p in env_after for p in property_names]):
            return [{'State': 'Error', 'Message': "Could not find property sources in environment"}]
        for ps in env_before.get('propertySources', env_before.get('bootstrapProperties', [])):
            try:
                if c in ps['properties']:
                    values_before[c] = ps['properties'][c]
            except TypeError:
                return [{'State': 'Error', 'Message': f"Error when reading environment before for {c}"}]
        for ps in env_after.get('propertySources', env_after.get('bootstrapProperties', [])):
            if c in ps['properties']:
                values_after[c] = ps['properties'][c]
    return [{
        'variable': c,
        'before': values_before.get(c, {'value': None})['value'],
        'after_value': values_after.get(c, {'value': None})['value'],
        'after_origin': values_after.get(c, {'origin': None}).get('origin')}
        for c in result_list]


def _send_results(ctx: ExtendedContext,
                  pod_to_refresh: str,
                  pod_env_before: requests.Response,
                  refresh_result: requests.Response,
                  pod_env_after: requests.Response):
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
