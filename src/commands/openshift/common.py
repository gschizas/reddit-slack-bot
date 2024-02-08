import functools
import os
import pathlib
import re

import click
from ruamel.yaml import YAML

from commands.extended_context import ExtendedContext

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
    if (permissions_config := config_file.with_suffix('.permissions.yml')).exists():
        with permissions_config.open(encoding='utf8') as f:
            permissions = yaml.load(f)
    else:
        permissions = []
    for env_name, env_cfg in config['environments'].items():
        if env_name in credentials:
            credentials_object = credentials[env_name]
            if isinstance(credentials_object, str):
                credentials_object = credentials_object.replace('\n', '')
            env_cfg['credentials'] = credentials_object
        if env_name in permissions:
            env_cfg['users'] = permissions[env_name]['users']
            env_cfg['channels'] = permissions[env_name]['channels']
    return config


class OpenShiftNamespace(click.ParamType):
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


def _get_chat_user_id(user, chat_team_name):
    return user.get(f'$slack-user-id.{chat_team_name}', user.get('$slack-user-id'))


def user_allowed(chat_team_name, chat_user_id, allowed_users):
    global all_users, all_users_last_update
    if '*' in allowed_users:
        return True
    if chat_user_id in allowed_users:
        return True
    allowed_groups = [g[1:] for g in allowed_users if g.startswith('@')]

    all_users_file = pathlib.Path('data/crowd_users.yml')
    if not all_users or all_users_file.stat().st_mtime != all_users_last_update:
        with all_users_file.open(encoding='utf8') as f:
            all_users = yaml.load(f)
        all_users_last_update = all_users_file.stat().st_mtime
    crowd_users = list(filter(lambda user: _get_chat_user_id(user, chat_team_name) == chat_user_id, all_users))
    if len(crowd_users) != 1:
        return False
    crowd_user = crowd_users[0]
    user_groups = crowd_user['groups']
    if set(allowed_groups).intersection(user_groups):
        return True
    return False


def check_security(func=None, *, config=None):
    if func is None:
        return functools.partial(check_security, config=config)

    default_config = config

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        ctx = args[0]
        action_name: str = ctx.obj['security_text'][ctx.command.name]
        action_name_proper = action_name.capitalize()
        namespace = kwargs.get('namespace')
        # default_config: dict = kwargs.pop('config', [])
        final_config = default_config if default_config else ctx.obj['config']
        cfg = final_config['environments'][namespace]
        # config = ctx.obj['config'][namespace]
        allowed_users = cfg['users']
        if not user_allowed(ctx.chat.team_name, ctx.chat.user_id, allowed_users):
            ctx.chat.send_text(f"You don't have permission to {action_name}.", is_error=True)
            return
        allowed_channels = cfg['channels']
        channel_name = ctx.chat.channel_name
        if channel_name not in allowed_channels:
            ctx.chat.send_text(f"{action_name_proper} commands are not allowed in {channel_name}", is_error=True)
            return
        return ctx.invoke(func, *args, **kwargs)

    return wrapper


def rangify(original_input_list, consolidate=True):
    REGEX = r'^(?P<prefix>[\w\.]+)(?:(?:\[(?P<index>\d+)\])(?P<suffix>[\w\.]*))?$'

    def _extract_index(an_item):
        """Extract actual name and index from a list item"""
        matches = re.match(REGEX, an_item)
        if not matches:
            return an_item, 0
        kind_prefix, index_text, kind_suffix = matches.groups()
        an_index = int(index_text or 0)
        a_kind = kind_prefix + (kind_suffix or '')
        return a_kind, an_index

    def _merge_consecutive_items(input_list):
        """Merge list items with the same kind and consecutive indexes"""
        output_list = []
        current_kind = ""
        current_start = None
        current_end = None
        for item in input_list:
            if "[" in item:
                # This is a kind with an index
                kind, index = _extract_index(item)
                if kind == current_kind and index == current_end + 1:
                    # This is part of an existing range
                    current_end = index
                    output_list[-1] = f"{kind}[{current_start}-{current_end}]"
                else:
                    # This is a new kind or a new range for the current kind
                    current_kind = kind
                    current_start = index
                    current_end = index
                    output_list.append(item)
            else:
                # This is a kind without an index
                current_kind = ""
                current_start = None
                current_end = None
                output_list.append(item)
        return output_list

    item_list = sorted(original_input_list, key=lambda line: _extract_index(line))
    if consolidate:
        return _merge_consecutive_items(item_list)
    else:
        return item_list


def env_config(ctx: ExtendedContext, namespace):
    return ctx.obj['config']['environments'][namespace]
