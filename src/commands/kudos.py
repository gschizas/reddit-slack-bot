import html
import os
import random
import re

import click
import psycopg

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext

SQL_KUDOS_INSERT = """\
INSERT INTO kudos (
   from_user, from_user_id,
   to_user, to_user_id,
   team_name, team_id,
   channel_name, channel_id,
   permalink, reason)
VALUES (
   %(sender_name)s, %(sender_id)s,
   %(recipient_name)s, %(recipient_id)s, 
   %(team_name)s, %(team_id)s,
   %(channel_name)s, %(channel_id)s,
   %(permalink)s, %(reason)s);
"""

SQL_KUDOS_VIEW = """\
SELECT to_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
AND channel_id = %(channel_id)s
GROUP BY to_user
ORDER BY 2 DESC;"""

SQL_KUDOS_VIEW_ALL = """\
SELECT to_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
GROUP BY to_user
ORDER BY 2 DESC;"""


@gyrobot.group('kudos',
               cls=DefaultCommandGroup,
               invoke_without_command=True,
               context_settings={
                   'ignore_unknown_options': True,
                   'allow_extra_args': True})
@click.pass_context
def kudos(ctx):
    """Add kudos to user.

    Syntax:
    kudos @username to give kudos to username
    kudos view to see all kudos so far
    kudos view 15 to see kudos given last 15 days
    """
    pass
    # if len(args) == 0:
    #     ctx.chat.send_text(("You need to specify a user "
    #                          "(i.e. @pikos_apikos) or "
    #                          "'view' to see leaderboard"), is_error=True)
    #     return
    # if ctx.chat.message.get('subtype') in ('message_replied', 'message_changed'):
    #     ctx.chat.send_ephemeral("Kudos not recorded. Replies and edits are ignored.")
    #     return
    # elif 'frostmaiden' in arg.lower():
    #     ctx.chat.send_text("You are welcome mortals! Have some more :snowflake:", icon_emoji=':snowflake:')
    #     return
    # else:
    #     chat.send_text(("You need to specify a user "
    #                     "(i.e. @pikos_apikos) or "
    #                     "'view' to see leaderboard"), is_error=True)


# @kudos.resultcallback(replace=True)
# @click.pass_context
# def kudos_epilogue(ctx: extended_context.ExtendedContext, result):
#     ctx.chat.send_text(f"the end {result!r}")


GIFTS = ['balloon', 'bear', 'goat', 'lollipop', 'cake', 'pancakes',
         'apple', 'pineapple', 'cherries', 'grapes', 'pizza', 'popcorn',
         'rose', 'tulip', 'baby_chick', 'beer', 'doughnut', 'cookie']


@kudos.command('give',
               default_command=True,
               context_settings={
                   'ignore_unknown_options': True,
                   'allow_extra_args': True})
@click.pass_context
def kudos_give(ctx: ExtendedContext):
    arg = ' '.join(ctx.args)
    reason = html.unescape(arg.split('>')[-1].strip())
    all_users = set(re.findall(r'<@(\w+)>', arg))

    for recipient_user_id in all_users:
        ctx.chat.slack_user_info(recipient_user_id)
        ctx.chat.slack_channel_info(ctx.chat.team_id, ctx.chat.channel_id)
        recipient_name = ctx.chat.users[recipient_user_id]['name']
        sender_name = ctx.chat.users[ctx.chat.user_id]['name']

        if recipient_user_id == ctx.chat.user_id:
            ctx.chat.send_text("You can't give kudos to yourself, silly!", is_error=True)
            continue

        if _record_kudos(ctx, sender_name, recipient_name, recipient_user_id, reason):
            text_to_send = f"Kudos from {sender_name} to {recipient_name}"
            give_gift = random.random()
            if reason.strip():
                # if re.search(r':\w+:', reason):
                #    reason = '. No cheating! Only I can send gifts!'
                #    give_gift = -1
                text_to_send += ' ' + reason
            if give_gift > 0.25:
                if not text_to_send.endswith('.'): text_to_send += '.'
                gift = random.choice(GIFTS)
                text_to_send += f" Have a :{gift}:"
            ctx.chat.send_text(text_to_send)
        else:
            ctx.chat.send_text("Kudos not recorded")


@kudos.command('view')
@click.argument('days_to_check', type=click.INT, default=14)
@click.option('-a', '--all', 'check_all_channels', is_flag=True, default=False)
@click.option('-x', '--excel', 'send_as_excel', is_flag=True, default=False)
@click.pass_context
def kudos_view(ctx: ExtendedContext, days_to_check, check_all_channels, send_as_excel):
    database_url = os.environ['KUDOS_DATABASE_URL']
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if check_all_channels:
                cur.execute(SQL_KUDOS_VIEW_ALL, {'days': days_to_check})
            else:
                cur.execute(SQL_KUDOS_VIEW, {'days': days_to_check, 'channel_id': ctx.chat.channel_id})
            rows = cur.fetchall()
            cols = [col.name for col in cur.description]
    if len(rows) == 0:
        ctx.chat.send_text("No kudos yet!")
    else:
        table = [dict(zip(cols, row)) for row in rows]
        ctx.chat.send_table(title="Kudos", table=table, send_as_excel=send_as_excel)


def _record_kudos(ctx: ExtendedContext, sender_name, recipient_name, recipient_user_id, reason):
    database_url = os.environ['KUDOS_DATABASE_URL']
    with psycopg.connect(database_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cmd_vars = {
                'sender_name': sender_name, 'sender_id': ctx.chat.user_id,
                'recipient_name': recipient_name, 'recipient_id': recipient_user_id,
                'team_name': ctx.chat.teams[ctx.chat.team_id]['name'], 'team_id': ctx.chat.team_id,
                'channel_name': ctx.chat.channels[ctx.chat.team_id][ctx.chat.channel_id],
                'channel_id': ctx.chat.channel_id,
                'permalink': ctx.chat.permalink['permalink'], 'reason': reason}
            cur.execute(SQL_KUDOS_INSERT, params=cmd_vars)
            success = cur.rowcount > 0
    return success
