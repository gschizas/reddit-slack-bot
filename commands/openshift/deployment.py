import json

import click

from commands import gyrobot, chat
from commands.openshift.api import get_deployments, change_pause_state
from commands.openshift.common import read_config, OpenShiftNamespace, check_security

_deployment_config = read_config('OPENSHIFT_DEPLOYMENT')


@gyrobot.group('deployment')
@click.pass_context
def deployment(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _deployment_config
    ctx.obj['security_text'] = {'list': 'list deployments', 'pause': 'pause deployment', 'resume': 'resume deployment'}


@deployment.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def list_deployments(ctx, namespace):
    deployments = get_deployments(ctx.obj['config'][namespace], namespace)
    chat(ctx).send_file(json.dumps(deployments).encode(), filename='deployments.json')


@deployment.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def pause_deployment(ctx, namespace):
    deployments = get_deployments(ctx.obj['config'][namespace], namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_pause_state(ctx.obj['config'][namespace], namespace, one_deployment['Name'], True))
    chat(ctx).send_file(json.dumps(result).encode(), filename='deployments.json')


@deployment.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def resume_deployment(ctx, namespace):
    deployments = get_deployments(ctx.obj['config'][namespace], namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_pause_state(ctx.obj['config'][namespace], namespace, one_deployment['Name'], None))
    chat(ctx).send_file(json.dumps(result).encode(), filename='deployments.json')
