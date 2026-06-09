"""Generic command-approval queue.

Commands decorated with :func:`requires_approval` do not run immediately. Instead,
the invocation (command name + click parameters) is serialized into the
``approval_requests`` table and a notification is sent. Designated approvers later
run the ``approvals`` command group to approve/reject pending requests; on approval
the original command body is executed via :func:`execute_approved`.

Storage is PostgreSQL (psycopg3), configured through ``APPROVAL_DATABASE_URL``.
Only commands whose click parameters are JSON-serializable can be gated.
"""
import functools
import os
import pathlib
from typing import Callable, List, Optional

import click
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.configuration import user_allowed
from bot_framework.yaml_wrapper import yaml

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

if 'APPROVAL_CONFIGURATION' not in os.environ:
    raise ImportError('APPROVAL_CONFIGURATION not found in environment')

# Roles distinguished *within* the single active environment (not separate
# environments): who may request approval-gated commands vs. who may approve them.
ROLE_REQUEST = 'request'
ROLE_APPROVE = 'approve'

# Each role maps to (users key, channels key) in the resolved permissions block.
_ROLE_KEYS: dict = {
    ROLE_REQUEST: ('requesters', 'request_channels'),
    ROLE_APPROVE: ('approvers', 'approve_channels'),
}


def _read_security_config() -> dict:
    """Load the approval security config (core YAML + sibling ``.permissions.yml``).

    The core file selects the single active ``environment`` and the self-approval
    policy; the permissions file holds, per environment, ``requesters`` /
    ``approvers`` (users), ``request_channels`` / ``approve_channels`` and the
    ``notify_channel``. Mirrors the file-resolution convention of
    :func:`backend.configuration.read_config`.
    """
    raw = os.environ['APPROVAL_CONFIGURATION']
    config_file = pathlib.Path(raw) if raw.startswith('/') else pathlib.Path('config') / raw
    with config_file.open(encoding='utf8') as f:
        core = yaml.load(f) or {}

    permissions = {}
    permissions_file = config_file.with_suffix('.permissions.yml')
    if permissions_file.exists():
        with permissions_file.open(encoding='utf8') as f:
            permissions = yaml.load(f) or {}

    environment = core.get('environment')
    if environment is None:
        if len(permissions) == 1:
            environment = next(iter(permissions))
        else:
            raise ValueError(
                "Approval config must set `environment:` when the permissions file "
                "defines more than one environment")
    env_perms = permissions.get(environment) or {}

    return {
        'environment': environment,
        'allow_self': bool(core.get('allow_self', False)),
        'requesters': env_perms.get('requesters', []),
        'request_channels': env_perms.get('request_channels', []),
        'approvers': env_perms.get('approvers', []),
        'approve_channels': env_perms.get('approve_channels', []),
        'notify_channel': env_perms.get('notify_channel'),
    }


# Resolved security configuration for the single active environment.
_SECURITY_CONFIG = _read_security_config()

# Registry of approval-gated click commands, keyed by command name. Populated by the
# requires_approval decorator at import time so requests can be re-invoked by name.
APPROVAL_COMMANDS: dict = {}

_schema_ready = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id                   SERIAL PRIMARY KEY,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_by_user_id TEXT,
    requested_by_name    TEXT,
    team_id              TEXT,
    team_name            TEXT,
    channel_id           TEXT,
    command              TEXT NOT NULL,
    params               JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary              TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    decided_by_user_id   TEXT,
    decided_by_name      TEXT,
    decided_at           TIMESTAMPTZ,
    result               TEXT
);
"""


def _connect():
    global _schema_ready
    conn = psycopg.connect(os.environ['APPROVAL_DATABASE_URL'], row_factory=dict_row)
    if not _schema_ready:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
        conn.commit()
        _schema_ready = True
    return conn


def enqueue(*, command: str, params: dict, summary: str,
            requested_by_user_id: str, requested_by_name: str,
            team_id: str, team_name: str, channel_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO approval_requests
                    (command, params, summary, requested_by_user_id, requested_by_name,
                     team_id, team_name, channel_id)
                VALUES (%(command)s, %(params)s, %(summary)s, %(user_id)s, %(name)s,
                        %(team_id)s, %(team_name)s, %(channel_id)s)
                RETURNING id;
                """,
                {'command': command, 'params': Jsonb(params), 'summary': summary,
                 'user_id': requested_by_user_id, 'name': requested_by_name,
                 'team_id': team_id, 'team_name': team_name, 'channel_id': channel_id})
            request_id = cur.fetchone()['id']
        conn.commit()
    return request_id


def get(request_id: int) -> Optional[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM approval_requests WHERE id = %s;", (request_id,))
            return cur.fetchone()


def list_pending() -> List[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY id;")
            return cur.fetchall()


def set_decision(request_id: int, status: str, decided_by_user_id: str,
                 decided_by_name: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_requests
                SET status = %(status)s,
                    decided_by_user_id = %(user_id)s,
                    decided_by_name = %(name)s,
                    decided_at = NOW()
                WHERE id = %(id)s;
                """,
                {'status': status, 'user_id': decided_by_user_id,
                 'name': decided_by_name, 'id': request_id})
        conn.commit()


def set_result(request_id: int, status: str, result: str) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE approval_requests SET status = %s, result = %s WHERE id = %s;",
                (status, result, request_id))
        conn.commit()


def _allow_self_approval() -> bool:
    return bool(_SECURITY_CONFIG.get('allow_self', False))


def _notify_channel() -> Optional[str]:
    channel = _SECURITY_CONFIG.get('notify_channel')
    return channel or None


def security_check(ctx, role: str, action_name: str) -> bool:
    """Validate the calling user and channel for ``role`` against the YAML config.

    Resembles :func:`backend.configuration.check_security`: checks the user with
    :func:`user_allowed` and verifies the channel is permitted (``*`` allows any).
    ``role`` selects requester vs. approver lists within the single active
    environment. Sends an error message and returns ``False`` when not permitted.
    """
    action_proper = action_name.capitalize()
    users_key, channels_key = _ROLE_KEYS[role]
    allowed_users = _SECURITY_CONFIG.get(users_key, [])
    if not user_allowed(ctx.chat.team_name, ctx.chat.user_id, allowed_users):
        ctx.chat.send_text(f"You don't have permission to {action_name}.", is_error=True)
        return False
    allowed_channels = _SECURITY_CONFIG.get(channels_key, [])
    channel_name = ctx.chat.channel_name
    if '*' not in allowed_channels and channel_name not in allowed_channels:
        ctx.chat.send_text(f"{action_proper} commands are not allowed in {channel_name}", is_error=True)
        return False
    return True


def check_approval_security(func: Callable = None, *, role: str = None):
    """``check_security``-style decorator for approval commands.

    Reads the human-readable action label from ``ctx.obj['security_text'][command]``
    and gates execution on :func:`security_check` for the given ``role``. Place it
    *below* ``@click.pass_context``.
    """
    if func is None:
        return functools.partial(check_approval_security, role=role)

    @functools.wraps(func)
    def wrapper(ctx, *args, **kwargs):
        action_name = ctx.obj['security_text'][ctx.command.name]
        if not security_check(ctx, role, action_name):
            return
        return ctx.invoke(func, ctx, *args, **kwargs)

    return wrapper


def _requester_name(ctx) -> str:
    try:
        return ctx.chat.get_user_info(ctx.chat.user_id).get('real_name', ctx.chat.user_id)
    except Exception:
        return ctx.chat.user_id


def requires_approval(func: Callable = None, *, summarize: Callable = None,
                      validate: Callable = None):
    """Decorator gating a click command behind the approval queue.

    Place *below* ``@click.pass_context`` so the wrapped callback receives ``ctx``.
    When invoked by a requester the command body is skipped and a pending request is
    enqueued; when re-invoked by an approver (``ctx.obj['_approved_execution']``) the
    real body runs.

    The command's click parameters must be JSON-serializable. Pass ``summarize`` to
    build a human-readable one-line summary from the params dict, and ``validate`` to
    reject bad requests before they are queued (return an error string to abort).
    """
    if func is None:
        return functools.partial(requires_approval, summarize=summarize, validate=validate)

    @functools.wraps(func)
    def wrapper(ctx, *args, **kwargs):
        if ctx.obj.get('_approved_execution'):
            return ctx.invoke(func, ctx, *args, **kwargs)

        command_name = ctx.command.name
        if not security_check(ctx, ROLE_REQUEST, f"request {command_name}"):
            return

        params = dict(ctx.params)

        if validate is not None and (error := validate(params)):
            ctx.chat.send_text(error, is_error=True)
            return

        summary = summarize(params) if summarize else _default_summary(command_name, params)
        request_id = enqueue(
            command=command_name, params=params, summary=summary,
            requested_by_user_id=ctx.chat.user_id, requested_by_name=_requester_name(ctx),
            team_id=ctx.chat.team_id, team_name=ctx.chat.team_name,
            channel_id=ctx.chat.channel_id)

        ctx.chat.send_text(
            f":hourglass_flowing_sand: Request *#{request_id}* queued for approval: {summary}")
        notify_channel = _notify_channel()
        if notify_channel:
            ctx.chat.send_text(
                f":inbox_tray: New approval request *#{request_id}*: {summary}\n"
                f"Use `{ctx.chat.bot_name} approvals approve {request_id}` to approve.",
                channel=notify_channel)
        return None

    APPROVAL_COMMANDS[func.__name__] = wrapper
    wrapper._approval_callback = func
    return wrapper


def _default_summary(command_name: str, params: dict) -> str:
    parts = ' '.join(f"{k}={v}" for k, v in params.items())
    return f"{command_name} {parts}".strip()


def execute_approved(approver_ctx, row: dict) -> str:
    """Re-invoke a stored request's command body and return its result string."""
    command_name = row['command']
    cmd = _find_command(command_name)
    if cmd is None:
        raise click.ClickException(f"Unknown approval command {command_name!r}")

    obj = dict(approver_ctx.obj)
    obj['_approved_execution'] = True
    obj['_approval_request'] = row

    sub_ctx = click.Context(cmd, info_name=command_name, obj=obj)
    sub_ctx.params = dict(row['params'])
    return cmd.invoke(sub_ctx)


def _find_command(command_name: str):
    from commands import gyrobot
    cmd = gyrobot.commands.get(command_name)
    if cmd is not None:
        return cmd
    if command_name in APPROVAL_COMMANDS:
        # Fall back to a synthetic command wrapping the registered callback.
        return click.Command(command_name, callback=click.pass_context(
            APPROVAL_COMMANDS[command_name]._approval_callback))
    return None
