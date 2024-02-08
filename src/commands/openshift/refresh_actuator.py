import json

import click
import requests
from cryptography import x509

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.common import read_config, OpenShiftNamespace, rangify, check_security
from commands.openshift.api_obsolete_2 import OpenShiftConnection, PortForwardProcess


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
    with OpenShiftConnection(ctx, namespace) as conn:
        for deployment in deployments:
            all_pods = conn.get_pods(deployment)
            if not all_pods:
                continue

            pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
            if len(pods_to_refresh) == 0:
                ctx.chat.send_text(f"Couldn't find any pods on {namespace} to view for {deployment}", is_error=True)
            pods_to_refresh_successful = 0
            for pod_to_refresh in pods_to_refresh:
                with PortForwardProcess(ctx, pod_to_refresh):
                    try:
                        empty_proxies = {'http': None, 'https': None}
                        pod_env_before = requests.get("http://localhost:9999/actuator/env",
                                                      proxies=empty_proxies, timeout=30)
                        refresh_result = requests.post("http://localhost:9999/actuator/refresh",
                                                       proxies=empty_proxies, timeout=30)
                        pod_env_after = requests.get("http://localhost:9999/actuator/env",
                                                     proxies=empty_proxies, timeout=30)
                        _send_results(ctx, pod_to_refresh, pod_env_before, refresh_result, pod_env_after)
                        pods_to_refresh_successful += 1
                    except requests.exceptions.ConnectionError as ex:
                        ctx.chat.send_text(f"Error when refreshing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
            ctx.chat.send_text(f"Refreshed {pods_to_refresh_successful}/{len(pods_to_refresh)} pods for {deployment}")


@actuator.command('view')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('deployments', type=str, nargs=-1)
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def view_actuator(ctx: ExtendedContext, namespace: str, deployments: list[str], excel: bool):
    with OpenShiftConnection(ctx, namespace) as conn:
        for deployment in deployments:
            all_pods = conn.get_pods(deployment)
            if not all_pods:
                continue

            pods_to_refresh = [pod['metadata']['name'] for pod in all_pods['items']]
            if len(pods_to_refresh) == 0:
                ctx.chat.send_text(f"Couldn't find any pods on {namespace} to view for {deployment}", is_error=True)
            pod_results = {}
            for pod_to_refresh in pods_to_refresh:
                with PortForwardProcess(ctx, pod_to_refresh):
                    try:
                        empty_proxies = {'http': None, 'https': None}
                        pod_env = requests.get("http://localhost:9999/actuator/env", proxies=empty_proxies, timeout=30)
                        pod_results[pod_to_refresh] = pod_env
                    except requests.exceptions.ConnectionError as ex:
                        ctx.chat.send_text(f"Error when viewing pod {pod_to_refresh}\n```{ex!r}```", is_error=True)
                        pod_results[pod_to_refresh] = [{'State': 'Error', 'Message': repr(ex)}]
            ctx.chat.send_tables('PodStatus', pod_results, excel)


@actuator.command('pods')
@click.argument('namespace', type=OpenShiftNamespace(_actuator_config()))
@click.argument('pod_name', type=str, required=False)
@click.pass_context
@check_security
def pods(ctx: ExtendedContext, namespace: str, pod_name: str = None):
    with OpenShiftConnection(ctx, namespace) as conn:
        all_pods = conn.get_pods(pod_name)

        fields = ["Deployment", "Name", "Ready", "Status", "Restarts", "Host IP", "Pod IP"]
        pods_list = [dict(zip(fields, [
            pod['metadata'].get('labels', {'deployment': ''}).get('deployment'),
            pod['metadata'].get('name', ''),
            f"",
            pod['status'].get('phase', ''),
            sum([cs.get('restartCount', 0) for cs in pod['status'].get('containerStatuses', [])]),
            pod['status'].get('hostIP', ''),
            pod['status'].get('podIP', '')])) for pod in all_pods['items']]
        ctx.chat.send_table(title=f"pods-{namespace}", table=pods_list)


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
                try:
                    if c in ps['properties']:
                        values_before[c] = ps['properties'][c]
                except TypeError:
                    ctx.chat.send_text(f"Error when reading environment before for {c}", is_error=True)
                    ctx.chat.send_file(pod_env_before_raw.content, filename='EnvBefore.json')
                    return
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

        if 'propertySources' in env_current:  # list of property sources, find the one called bootstrapProperties
            property_sources = env_current.get('propertySources')
            bootstrap_properties = [prop for prop in property_sources if prop['name'] == 'bootstrapProperties']
            property_root = bootstrap_properties[0]['properties']
            complex_properties = True
        elif 'bootstrapProperties' in env_current:  # only one dictionary, get to it directly
            property_root = env_current.get('bootstrapProperties')
            complex_properties = False
        else:
            ctx.chat.send_text("Could not find property sources in environment", is_error=True)
            ctx.chat.send_file(pod_env_raw.content, filename='EnvCurrent.json')
            return

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

    if full_env := _environment_table(pod_env):
        ctx.chat.send_table(f"Changes for pod {pod_to_refresh}", full_env, send_as_excel=excel)
