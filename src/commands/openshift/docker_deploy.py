#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocp-deployer.py: Deployment script for OpenShift Container Platform"""

import click
import docker
import docker.errors

from commands import gyrobot
from commands.extended_context import ExtendedContext
from commands.openshift.common import read_config, check_security

# from ocpconfig import environments, environment_name, dry_run
# from slackconfig import channel_deployment, username_deployment

_docker_config = read_config('DOCKER_DEPLOY_CONFIGURATION')


@gyrobot.group('docker')
@click.pass_context
def docker(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _docker_config
    ctx.obj['security_text'] = {'deploy': 'deploy'}


class DockerEnvironment(click.ParamType):
    _force_upper: bool
    name = 'namespace'
    _config = {}

    def __init__(self, config, force_upper: bool = None) -> None:
        super().__init__()
        self._config = config
        self._force_upper = force_upper or False

    def convert(self, value, param, ctx) -> str:
        valid_environments = [e.lower() for e in self._config['environments']]
        valid_environments_text = ', '.join(valid_environments)
        if value.lower() not in valid_environments:
            self.fail(
                f"{value} is not a valid namespace. Try one of those: {valid_environments_text}",
                param,
                ctx)
        return value.upper() if self._force_upper else value.lower()


@docker.command('deploy')
@click.argument('microservice')
@click.argument('version')
@click.argument('source_env', type=DockerEnvironment(_docker_config))
@click.argument('target_env', type=DockerEnvironment(_docker_config))
@click.option('dry_run', '-d', '--dry-run', is_flag=True, default=False, help='Do not push image to target env')
@click.pass_context
@check_security
def deploy(ctx: ExtendedContext, microservice, version, source_env: DockerEnvironment, target_env: DockerEnvironment, dry_run=False):
    """Pull microservice image from source env and push to target env"""
    ctx.chat.send_text("Not implemented yet!", is_error=True)

    source_registry_prefix_template = environments[source_env]['registry']
    target_registry_prefix_template = environments[target_env]['registry']

    source_image = source_registry_prefix_template.substitute(
        env=environment_name.get(source_env, source_env)) + microservice
    target_image = target_registry_prefix_template.substitute(
        env=environment_name.get(target_env, target_env)) + microservice

    client = docker.from_env()
    source_auth_config = {"username": environments[source_env]['user'], "password": environments[source_env]['secret']}
    target_auth_config = {"username": environments[target_env]['user'], "password": environments[target_env]['secret']}
    tag_with_env_name = environments[target_env]['tagWithEnv'].lower() == 'true'

    ctx.chat.send_text(f"Pulling {source_image}:{version} from {source_env}")

    image = None
    try:
        if not dry_run:
            image = client.images.pull(source_image, version, auth_config=source_auth_config)
            image.tag(target_image, version)

        msg = f"Tagged, pushing {target_image}:{version} to {target_env} ... "
        if not dry_run:
            msg += "Success" if client.images.push(target_image, version, auth_config=target_auth_config) else "Failed"
            client.images.remove(target_image + ":" + version)
        else:
            msg += "(dry run)"
        ctx.chat.send_text(msg)

        if tag_with_env_name:
            target_env = environment_name[target_env] if target_env in environment_name else target_env
            msg = f"Tagged, pushing {target_image}:{target_env} to {target_env} ... "
            if not dry_run:
                image.tag(target_image, target_env)
                msg += "Success" if client.images.push(target_image, target_env,
                                                       auth_config=target_auth_config) else "Failed"
                client.images.remove(target_image + ":" + target_env)
            else:
                msg += "(dry run)"
            ctx.chat.send_text(msg)

        if not dry_run:
            client.images.remove(source_image + ":" + version)
    except docker.errors.APIError as e:
        ctx.chat.send_text(f"*Failed with error {e}*")


def _handle_message(ctx: ExtendedContext, m: dict):
    """Handle message"""
    channel = m['channel']
    if channel != channel_deployment:
        return

    if 'message' in m:
        m = m['message']

    if 'username' in m and m['username'] == username_deployment:
        return

    if 'subtype' in m and m['subtype'] == 'message_deleted':
        return

    text = m['text']
    parts = text.split('/')

    if len(parts) != 4:
        ctx.chat.send_text("*Usage: <microservice>/<version>/<source_env>/<target_env>*")
        ctx.chat.send_text(f"*Environments supported: {list(environments.keys())}*")
        return
    if not parts[2] in environments.keys():
        ctx.chat.send_text(f"*{parts[2]}* environment not recognized")
        return
    if not parts[3] in environments.keys():
        ctx.chat.send_text(f"*{parts[3]}* environment not recognized")
        return

    deploy(parts[0], parts[1], parts[2], parts[3], dry_run=dry_run)
