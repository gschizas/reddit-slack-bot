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
from typing import Callable, List, Optional

import click
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.configuration import user_allowed

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

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


def _approvers() -> list:
    return [u for u in os.environ.get('APPROVAL_APPROVERS', '').split(',') if u]


def _requesters() -> list:
    raw = os.environ.get('APPROVAL_REQUESTERS', '*')
    return [u for u in raw.split(',') if u] or ['*']


def can_approve(ctx) -> bool:
    return user_allowed(ctx.chat.team_name, ctx.chat.user_id, _approvers())


def can_request(ctx) -> bool:
    return user_allowed(ctx.chat.team_name, ctx.chat.user_id, _requesters())


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

        if not can_request(ctx):
            ctx.chat.send_text("You don't have permission to issue this command.", is_error=True)
            return

        params = dict(ctx.params)
        command_name = ctx.command.name

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
        notify_channel = os.environ.get('APPROVAL_NOTIFY_CHANNEL')
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
