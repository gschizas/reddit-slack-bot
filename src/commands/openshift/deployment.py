import json
from typing import Dict, List

import click

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.api import KubernetesConnection
from commands.openshift.common import read_config, OpenShiftNamespace, check_security

REMOVE_DEPLOYMENT_KEYS = ['Containers', 'Images', 'Selector']
_deployment_config = read_config('OPENSHIFT_DEPLOYMENT')


@gyrobot.group('deployment')
@click.pass_context
def deployment(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _deployment_config
    ctx.obj['security_text'] = {'list': 'list deployments', 'pause': 'pause deployment', 'resume': 'resume deployment'}


@deployment.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def list_deployments(ctx: ExtendedContext, namespace: str, excel: bool):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
    if not excel:
        deployment_table = [{k: v for k, v in dep.items() if k not in REMOVE_DEPLOYMENT_KEYS} for dep in deployments]
    else:
        deployment_table = deployments.items()
    ctx.chat.send_table(title='deployments', table=deployment_table, send_as_excel=excel)


@deployment.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def pause_deployment(ctx: ExtendedContext, namespace: str, excel: bool):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
        result = []
        for one_deployment in deployments:
            result.append(k8s.apps_v1_api.patch_namespaced_deployment(
                one_deployment.metadata.name, k8s.project_name,
                {'spec': {'paused': True}}))
        result_markdown = _make_deployments_table(result)
    ctx.chat.send_file(json.dumps(result).encode(), filename='deployments.json')
    ctx.chat.send_table(title='deployments', table=result_markdown, send_as_excel=excel)


@deployment.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def resume_deployment(ctx: ExtendedContext, namespace, excel: bool):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
    result = []
    for one_deployment in deployments:
        result.append(k8s.apps_v1_api.patch_namespaced_deployment(one_deployment.metadata.name, k8s.project_name,
                                                                  {'spec': {'paused': None}}))
    ctx.chat.send_file(json.dumps(result).encode(), filename='deployments.json')
    ctx.chat.send_table(title='deployments', table=_make_deployments_table(result), send_as_excel=excel)
    ctx.chat.send_file(json.dumps(result).encode(), filename='deployments.json')


def _make_deployments_table(result) -> List[Dict]:
    return [{
        'Namespace': dep.metadata.namespace,
        'Name': dep.metadata.name,
        'Replicas': dep.status.replicas,
        'Updated Replicas': dep.status.updated_replicas,
        'Ready Replicas': dep.status.ready_replicas,
        'Available Replicas': dep.status.available_replicas} for dep in result]
