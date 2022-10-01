import os
import pathlib
from functools import update_wrapper

import click
from ruamel.yaml import YAML

from commands import chat

yaml = YAML()
all_users = []
all_users_last_update = 0


def read_config(env_var):
    if os.environ[env_var].startswith('/'):
        config_file = pathlib.Path(os.environ[env_var])
    else:
        config_file = pathlib.Path('config') / os.environ[env_var]
    with config_file.open(encoding='utf8') as f:
        config = yaml.load(f)
    with config_file.with_suffix('.credentials.yml').open(encoding='utf8') as f:
        credentials = yaml.load(f)
    for env in config:
        if env in credentials:
            config[env]['openshift_token'] = credentials[env]
    return config


class OpenShiftNamespace(click.ParamType):
    name = 'namespace'
    _config = {}

    def __init__(self, config) -> None:
        super().__init__()
        self._config = config

    def convert(self, value, param, ctx) -> str:
        valid_environments = [e.lower() for e in self._config]
        valid_environments_text = ', '.join(valid_environments)
        if value.lower() not in valid_environments:
            self.fail(
                f"{value} is not a valid namespace. Try one of those: {valid_environments_text}",
                param,
                ctx)
        return value.lower()


def user_allowed(slack_user_id, allowed_users):
    global all_users, all_users_last_update
    if '*' in allowed_users:
        return True
    if slack_user_id in allowed_users:
        return True
    allowed_groups = [g[1:] for g in allowed_users if g.startswith('@')]

    all_users_file = pathlib.Path('data/crowd_users.yml')
    if all_users is None or all_users_file.stat().st_mtime != all_users_last_update:
        with all_users_file.open(encoding='utf8') as f:
            all_users = yaml.load(f)
        all_users_last_update = all_users_file.stat().st_mtime
    crowd_users = list(filter(lambda x: x.get('$slack-user-id') == slack_user_id, all_users))
    if len(crowd_users) != 1:
        return False
    crowd_user = crowd_users[0]
    user_groups = crowd_user['groups']
    if set(allowed_groups).intersection(user_groups):
        return True
    return False


def check_security(f):
    def check_security_inner(ctx, *args, **kwargs):
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
