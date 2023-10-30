import os

import click
import psycopg
from tabulate import tabulate

from commands import gyrobot
from commands.extended_context import ExtendedContext

SQL_TOO_MANY_POSTS = """\
                select
                    author,
                    count(*)
                from
                    public.submissions
                where
                    created > (now() at time zone 'utc' - interval '1 day')
                group by
                    author
                having
                    count(*) > 2
                order by
                    count(*) desc;"""


@gyrobot.command('too_many_posts')
@click.pass_context
def too_many_posts(ctx: ExtendedContext):
    """Show users with too many posts in the last 24 hours"""
    with psycopg.connect(os.environ['GYROBOT_DATABASE_URL']) as conn:
        with conn.cursor() as cur:
            rows_raw = cur.execute(SQL_TOO_MANY_POSTS)
            rows = rows_raw.fetchall()
            headers = [col.name for col in rows_raw.description]
    result_table = [dict(zip(headers, row)) for row in rows]
    ctx.chat.send_table('too_many_posts', result_table)
