import json
from functools import update_wrapper

import click

from commands import gyrobot, chat, logger
from commands.openshift.api import get_deployments, change_pause_state
from commands.openshift.common import read_config, user_allowed, OpenShiftNamespace

_deployment_config = read_config('OPENSHIFT_DEPLOYMENT')


def extras(*args, **kwargs):
    def action_name_inner(func):
        func.action_name = kwargs['action_text']
        return func(*args, **kwargs)

    return action_name_inner


def check_security(f):
    def check_security_inner(ctx, *args, **kwargs):
        logger(ctx).debug("hello")
        action_name: str = ctx.obj['security_text'][ctx.command.name]
        action_name_proper = action_name.capitalize()
        namespace = kwargs.get('namespace')
        config = ctx.obj['config'][namespace]
        allowed_users = config['users']
        if not user_allowed(chat(ctx).user_id, allowed_users):
            chat(ctx).send_text(f"You don't have permission to {action_name}.", is_error=True)
            return
        allowed_channels = config['channels']
        channel_name = chat(ctx).channel_name
        if channel_name not in allowed_channels:
            chat(ctx).send_text(f"{action_name_proper} commands are not allowed in {channel_name}", is_error=True)
            return
        return ctx.invoke(f, ctx, *args, **kwargs)

    return update_wrapper(check_security_inner, f)


@gyrobot.group('deployment')
@click.pass_context
def deployment(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _deployment_config
    ctx.obj['security_text'] = {
        'list': 'list deployments',
        'pause': 'pause deployment',
        'resume': 'resume deployment'
    }


@deployment.command('list')
# @click.decorators.pass_meta_key('list deployments')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def list_deployments(ctx, namespace):
    deployments = get_deployments(ctx.obj['config'][namespace], namespace)
    chat(ctx).send_file(json.dumps(deployments).encode(), filename='deployments.json')

# , context_settings={'obj': {'test': '123'}


@deployment.command('pause')
# @click.decorators.pass_meta_key('pause deployment')
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
# @click.decorators.pass_meta_key('resume deployment')
@click.argument('namespace', type=OpenShiftNamespace(_deployment_config))
@click.pass_context
@check_security
def resume_deployment(ctx, namespace):
    deployments = get_deployments(ctx.obj['config'][namespace], namespace)
    result = []
    for one_deployment in deployments:
        result.append(change_pause_state(ctx.obj['config'][namespace], namespace, one_deployment['Name'], None))
    chat(ctx).send_file(json.dumps(result).encode(), filename='deployments.json')
