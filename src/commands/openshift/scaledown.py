import os

import click
from ruamel.yaml import YAML

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext
from commands.openshift.api import KubernetesConnection
from commands.openshift.common import OpenShiftNamespace
from backend.configuration import read_config, check_security

if 'OPENSHIFT_SCALEDOWN' not in os.environ:
    raise ImportError('OPENSHIFT_SCALEDOWN not found in environment')

yaml = YAML()
all_users = []
all_users_last_update = 0


def _scaledown_config():
    env_var = 'OPENSHIFT_SCALEDOWN'
    return read_config(env_var)


@gyrobot.group('scaledown', cls=DefaultCommandGroup)
@click.pass_context
def scaledown(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _scaledown_config()
    ctx.obj['security_text'] = {'do': 'scale down kubernetes objects'}


@scaledown.command(default_command=True,
                   context_settings={
                       'ignore_unknown_options': True,
                       'allow_extra_args': True})
@click.argument('namespace', type=OpenShiftNamespace(_scaledown_config()))
@click.pass_context
def scaledown_default(ctx: ExtendedContext, namespace: str):
    ctx.forward(scaledown_do)


@scaledown.command('do')
@click.argument('namespace', type=OpenShiftNamespace(_scaledown_config()))
@click.pass_context
@check_security
def scaledown_do(ctx: ExtendedContext, namespace):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments_to_scaledown = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
        if len(deployments_to_scaledown.items) == 0:
            ctx.chat.send_text(f"Couldn't find any deployments on {namespace} to scale down", is_error=True)
            return

        results = []
        for deployment_to_scaledown in deployments_to_scaledown.items:
            if deployment_to_scaledown in ctx.obj['config'].get('~deployments', []): continue  # ignore deployment
            result = k8s.apps_v1_api.patch_namespaced_replica_set_scale(
                deployment_to_scaledown.metadata.name, k8s.project_name,
                {'spec': {'replicas': 0}})
            results.append(result)

        for resource_to_scaledown in deployments_to_scaledown.items:
            if resource_to_scaledown in ctx.obj['config'].get('~statefulsets', []): continue  # ignore statefulset
            result = k8s.apps_v1_api.patch_namespaced_stateful_set_scale(
                resource_to_scaledown.metadata.name, k8s.project_name,
                {'spec': {'replicas': 0}})
            results.append(result)

        ctx.chat.send_table(title=f"scaledown-{k8s.project_name}", table=results)
