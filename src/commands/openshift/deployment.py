import os
from typing import Dict, List

import click

from backend.constants import TableFormat
from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.api import KubernetesConnection
from commands.openshift.common import OpenShiftNamespace
from backend.configuration import read_config, check_security

if 'OPENSHIFT_DEPLOYMENT' not in os.environ:
    raise ImportError('OPENSHIFT_DEPLOYMENT not found in environment')

_deployment_config = read_config('OPENSHIFT_DEPLOYMENT')


@gyrobot.group('deployment')
@click.pass_context
def deployment(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _deployment_config
    ctx.obj['security_text'] = {'list': 'list deployments', 'pause': 'pause deployment', 'resume': 'resume deployment'}


@deployment.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-f', '--format', type=TableFormat, default=TableFormat.TABLE)
@click.pass_context
@check_security
def list_deployments(ctx: ExtendedContext, namespace: str, table_format: TableFormat=TableFormat.TABLE):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
    deployments_table = _make_deployments_table(deployments.items)
    ctx.chat.send_table(title='deployments', table=deployments_table, table_format=table_format)


@deployment.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-f', '--format', type=TableFormat, default=TableFormat.TABLE)
@click.pass_context
@check_security
def pause_deployment(ctx: ExtendedContext, namespace: str, table_format: TableFormat=TableFormat.TABLE):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
        result = []
        for one_deployment in deployments.items:
            result.append(k8s.apps_v1_api.patch_namespaced_deployment(
                one_deployment.metadata.name, k8s.project_name,
                {'spec': {'paused': True}}))
        result_markdown = _make_deployments_table(result)
    ctx.chat.send_table(title='deployments', table=result_markdown, table_format=table_format)


@deployment.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-f', '--format', type=TableFormat, default=TableFormat.TABLE)
@click.pass_context
@check_security
def resume_deployment(ctx: ExtendedContext, namespace, table_format: TableFormat=TableFormat.TABLE):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
        result = []
        for one_deployment in deployments.items:
            result.append(k8s.apps_v1_api.patch_namespaced_deployment(
                one_deployment.metadata.name, k8s.project_name,
                {'spec': {'paused': None}}))
    ctx.chat.send_table(title='deployments', table=_make_deployments_table(result), table_format=table_format)


def _make_deployments_table(result) -> List[Dict]:
    return [{
        'Namespace': dep.metadata.namespace,
        'Name': dep.metadata.name,
        'Created': dep.metadata.creation_timestamp,
        'Replicas': dep.status.replicas,
        'Updated Replicas': dep.status.updated_replicas,
        'Ready Replicas': dep.status.ready_replicas,
        'Available Replicas': dep.status.available_replicas,
        'Paused': dep.spec.paused} for dep in result]
