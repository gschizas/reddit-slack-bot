import json
from typing import Dict, List

import click

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.api import get_deployments, change_deployment_pause_state
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
    deployments = get_deployments(ctx, namespace)
    if not excel:
        deployments = [{k: v for k, v in dep.items() if k not in REMOVE_DEPLOYMENT_KEYS} for dep in deployments]
    ctx.chat.send_table(title='deployments', table=deployments, send_as_excel=excel)


@deployment.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def pause_deployment(ctx: ExtendedContext, namespace: str):
    deployments = get_deployments(ctx, namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_deployment_pause_state(ctx, namespace, one_deployment['Name'], True))
    result_markdown = _make_deployments_table(result)
    ctx.chat.send_table(title='deployments.md', table=result_markdown)
    ctx.chat.send_file(json.dumps(result).encode(), filename='deployments.json')


@deployment.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def resume_deployment(ctx: ExtendedContext, namespace):
    deployments = get_deployments(ctx, namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_deployment_pause_state(ctx, namespace, one_deployment['Name'], None))
    ctx.chat.send_table(title='deployments', table=_make_deployments_table(result))
    ctx.chat.send_file(json.dumps(result).encode(), filename='deployments.json')


def _make_deployments_table(result) -> List[Dict]:
    return [{
        'Namespace': dep['metadata']['namespace'],
        'Name': dep['metadata']['name'],
        'Replicas': dep['status'].get('replicas'),
        'Updated Replicas': dep['status'].get('updatedReplicas'),
        'Ready Replicas': dep['status'].get('readyReplicas'),
        'Available Replicas': dep['status'].get('availableReplicas')} for dep in result]
