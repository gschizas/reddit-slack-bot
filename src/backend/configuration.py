import functools
import os
import pathlib

from ruamel.yaml import YAML


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
    with (pathlib.Path('config') / 'kubernetes_servers.yml').open(encoding='utf8') as f:
        servers = yaml.load(f)
    for env_name, env_cfg in config['environments'].items():
        if env_cfg is None:
            env_cfg = config['environments'][env_name] = {}
        if env_name in credentials:
            credentials_object = credentials[env_name]
            if isinstance(credentials_object, str):
                credentials_object = credentials_object.replace('\n', '')
            env_cfg['credentials'] = credentials_object
        if env_name in permissions:
            env_cfg['users'] = permissions[env_name]['users']
            env_cfg['channels'] = permissions[env_name]['channels']
        if env_name in servers:
            env_cfg['url'] = servers[env_name].get('url')
            env_cfg['cert'] = servers[env_name].get('cert')
            env_cfg['project_name'] = servers[env_name].get('project_name')
    return config


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


yaml = YAML()


def _get_chat_user_id(user, chat_team_name):
    return user.get(f'$slack-user-id.{chat_team_name}', user.get('$slack-user-id'))
