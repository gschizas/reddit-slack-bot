import functools
import json
import os
import pathlib
import re
import subprocess

import click
from ruamel.yaml import YAML

from commands import chat, logger

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
    for env_name, env_config in config['environments'].items():
        if env_name in credentials:
            credentials_object = credentials[env_name]
            if isinstance(credentials_object, str):
                credentials_object = credentials_object.replace('\n', '')
            env_config['credentials'] = credentials_object
        if env_name in permissions:
            env_config['users'] = permissions[env_name]['users']
            env_config['channels'] = permissions[env_name]['channels']
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


def user_allowed(slack_user_id, allowed_users):
    global all_users, all_users_last_update
    if '*' in allowed_users:
        return True
    if slack_user_id in allowed_users:
        return True
    allowed_groups = [g[1:] for g in allowed_users if g.startswith('@')]

    all_users_file = pathlib.Path('data/crowd_users.yml')
    if not all_users or all_users_file.stat().st_mtime != all_users_last_update:
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
        if not user_allowed(chat(ctx).user_id, allowed_users):
            chat(ctx).send_text(f"You don't have permission to {action_name}.", is_error=True)
            return
        allowed_channels = cfg['channels']
        channel_name = chat(ctx).channel_name
        if channel_name not in allowed_channels:
            chat(ctx).send_text(f"{action_name_proper} commands are not allowed in {channel_name}", is_error=True)
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


def azure_login(ctx, service_principal_id, service_principal_key, tenant_id, resource_group, cluster_name):
    az_cli = os.environ.get('AZ_CLI_EXECUTABLE', 'az')
    result_text = ""
    command_arguments = [
        az_cli, 'login',
        '--service-principal',
        '--username', service_principal_id,
        '--password', service_principal_key,
        '--tenant', tenant_id]
    logger(ctx).info(command_arguments)
    login_cmd = subprocess.run(command_arguments, capture_output=True)
    chat(ctx).send_text(f"Logging in to Azure...")
    login_result = json.loads(login_cmd.stdout)
    # chat(ctx).send_file(login_cmd.stdout, filename='login.json')
    chat(ctx).send_text(
        f"{login_result[0]['cloudName']} : {login_result[0]['name']} : {login_result[0]['user']['type']}")
    set_project_args = [
        az_cli, 'aks', 'get-credentials',
        '--overwrite-existing',
        '--name', cluster_name,
        '--resource-group', resource_group]
    logger(ctx).info(set_project_args)
    set_project_cmd = subprocess.run(set_project_args, capture_output=True)
    result_text += set_project_cmd.stdout.decode() + '\n' + set_project_cmd.stderr.decode() + '\n\n'
    convert_login_args = ['kubelogin', 'convert-kubeconfig', '-l', 'azurecli']
    convert_login_cmd = subprocess.run(convert_login_args, capture_output=True)
    result_text += convert_login_cmd.stdout.decode() + '\n' + convert_login_cmd.stderr.decode() + '\n\n'
    return result_text


def env_config(ctx, namespace):
    return ctx.obj['config']['environments'][namespace]
