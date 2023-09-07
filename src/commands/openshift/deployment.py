import json

import click
import pandas as pd
import io
from tabulate import tabulate

from commands import gyrobot, chat
from commands.openshift.api import get_deployments, change_deployment_pause_state
from commands.openshift.common import read_config, OpenShiftNamespace, check_security, env_config

REMOVE_DEPLOYMENT_KEYS = ['Containers', 'Images', 'Selector']
_deployment_config = read_config('OPENSHIFT_DEPLOYMENT')


@gyrobot.group('deployment')
@click.pass_context
def deployment(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _deployment_config
    ctx.obj['security_text'] = {'list': 'list deployments', 'pause': 'pause deployment', 'resume': 'resume deployment'}


@deployment.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def list_deployments(ctx: click.Context, namespace: str, excel: bool):
    deployments = get_deployments(ctx, namespace)
    if excel:
        deployments_df = pd.DataFrame(deployments)
        with io.BytesIO() as deployments_output:
            deployments_df.reset_index(drop=True).to_excel(deployments_output)
            chat(ctx).send_file(deployments_output.getvalue(), filename='deployments.xlsx')
    else:
        deployments = [{k: v for k, v in dep.items() if k not in REMOVE_DEPLOYMENT_KEYS} for dep in deployments]
        deployments_markdown = tabulate(deployments, headers='keys', tablefmt='fancy_outline')
        chat(ctx).send_file(deployments_markdown.encode(), filename='deployments.md')


@deployment.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def pause_deployment(ctx: click.Context, namespace: str):
    deployments = get_deployments(ctx, namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_deployment_pause_state(ctx, namespace, one_deployment['Name'], True))
    result_markdown = _make_deployments_table(result)
    chat(ctx).send_file(result_markdown.encode(), filename='deployments.md')
    chat(ctx).send_file(json.dumps(result).encode(), filename='deployments.json')


@deployment.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def resume_deployment(ctx, namespace):
    deployments = get_deployments(ctx, namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_deployment_pause_state(ctx, namespace, one_deployment['Name'], None))
    result_markdown = _make_deployments_table(result)
    chat(ctx).send_file(result_markdown.encode(), filename='deployments.md')
    chat(ctx).send_file(json.dumps(result).encode(), filename='deployments.json')


def _make_deployments_table(result) -> str:
    result_table = [{
        'Namespace': dep['metadata']['namespace'],
        'Name': dep['metadata']['name'],
        'Replicas': dep['status'].get('replicas'),
        'Updated Replicas': dep['status'].get('updatedReplicas'),
        'Ready Replicas': dep['status'].get('readyReplicas'),
        'Available Replicas': dep['status'].get('availableReplicas')} for dep in result]
    return tabulate(result_table, headers='keys', tablefmt='fancy_outline')
