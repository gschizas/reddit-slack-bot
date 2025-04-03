import html
import io
import os
import random
import re

import click
import imageio.v3 as imageio
import numpy as np
import psycopg
from PIL import Image, ImageDraw, ImageFont

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext

if 'KUDOS_DATABASE_URL' not in os.environ:
    raise ImportError('KUDOS_DATABASE_URL not found in environment')

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

SQL_KUDOS_VIEW_GIVERS = """\
SELECT from_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
AND channel_id = %(channel_id)s
GROUP BY from_user
ORDER BY 2 DESC;"""

SQL_KUDOS_VIEW_GIVERS_ALL = """\
SELECT from_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
GROUP BY from_user
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


GIFTS = ['balloon', 'bear', 'goat', 'lollipop', 'cake', 'pancakes',
         'apple', 'pineapple', 'cherries', 'grapes', 'pizza', 'popcorn',
         'rose', 'tulip', 'baby_chick', 'beer', 'doughnut', 'cookie']

EXTRACT_SLACK_ID = re.compile(r'<(?:[#@])(?P<id>\w+)(?:\|)?(?:[-.\w]+)?>')


@kudos.command('give',
               default_command=True,
               context_settings={
                   'ignore_unknown_options': True,
                   'allow_extra_args': True})
@click.pass_context
def kudos_give(ctx: ExtendedContext):
    arg = ' '.join(ctx.args)
    reason = html.unescape(arg.split('>')[-1].strip())
    all_users = set(EXTRACT_SLACK_ID.findall(arg))

    if len(all_users) == 0:
        ctx.chat.send_text("Who are you giving kudos to?", is_error=True)
        return

    final_text = ""

    for recipient_user_id in all_users:
        # ctx.chat.preload(recipient_user_id, ctx.chat.team_id, ctx.message.channel_id)
        recipient_name = ctx.chat.get_user_info(recipient_user_id)['name']
        sender_name = ctx.chat.get_user_info(ctx.chat.user_id)['name']

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
            final_text += text_to_send + '\n'
        else:
            final_text += f"⚠️Kudos not recorded for {recipient_name}" + '\n'
    if final_text == "":
        final_text = "(empty text)"
    ctx.chat.send_text(final_text)


@kudos.command('view')
@click.argument('days_to_check', type=click.INT, default=14)
@click.argument('channel', default='')
@click.option('-g', '--givers', 'show_givers', is_flag=True, default=False)
@click.option('-t', '--text', 'output_format', flag_value='text', default=True)
@click.option('-x', '--excel', 'output_format', flag_value='excel')
@click.option('-v', '--video', 'output_format', flag_value='video')
@click.option('-i', '--image', 'output_format', flag_value='image')
@click.pass_context
def kudos_view(ctx: ExtendedContext, days_to_check: int, channel: str,
               show_givers: bool,
               output_format: str):
    database_url = os.environ['KUDOS_DATABASE_URL']
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if channel == '*':
                sql = SQL_KUDOS_VIEW_ALL if not show_givers else SQL_KUDOS_VIEW_GIVERS_ALL
                cur.execute(sql, {'days': days_to_check})
            else:
                channel_id = ctx.chat.channel_id if channel == '' else (EXTRACT_SLACK_ID.findall(channel) or [''])[0]
                sql = SQL_KUDOS_VIEW if not show_givers else SQL_KUDOS_VIEW_GIVERS
                cur.execute(sql, {'days': days_to_check, 'channel_id': channel_id})
            rows = cur.fetchall()
            cols = [col.name for col in cur.description]
    if len(rows) == 0:
        ctx.chat.send_text("No kudos yet!")
    else:
        table = [dict(zip(cols, row)) for row in rows]
        if output_format == 'video':
            video_file = _create_kudos_video(table)
            ctx.chat.send_file(video_file, title="Kudos", filename="kudos.mp4")
        elif output_format == 'image':
            image_file = _create_kudos_image(table)
            ctx.chat.send_file(image_file, title="Kudos", filename="kudos.png")
        elif output_format == 'text':
            ctx.chat.send_table(title="Kudos", table=table, send_as_excel=False)
        else:
            ctx.chat.send_table(title="Kudos", table=table, send_as_excel=True)


def _create_kudos_image(high_scores):
    width, height = 320, 480

    high_scores = high_scores[:16]

    score_font = ImageFont.truetype("img/kudos/amstrad_cpc464.ttf", 12)
    title_font = ImageFont.truetype("img/kudos/amstrad_cpc464.ttf", 18)

    # Create a new image
    bg = Image.open("img/kudos/wallpaper.jpg").resize((width, height))
    image = Image.new("RGB", (width, height), (0, 0, 0))
    image.paste(bg, (0, 0))
    draw = ImageDraw.Draw(image)

    draw.text((50, 50), "::: Kudos :::", fill=(255, 255, 255), font=title_font)

    # Draw the high scores
    for i, player_and_score in enumerate(high_scores):
        player, score = player_and_score['User'], player_and_score['kudos']
        score_text = f"{score:> 4} {player}"
        draw.text(
            (21, 101 + i * 20),
            score_text,
            fill=(0, 0, 0),
            font=score_font,
        )
        draw.text(
            (20, 100 + i * 20),
            score_text,
            fill=(255, 255, 255),
            font=score_font,
        )

    # Save the image to a BytesIO object
    byte_arr = io.BytesIO()
    image.save(byte_arr, format='PNG')

    # Get the byte array
    byte_arr = byte_arr.getvalue()

    return byte_arr


def _create_kudos_video(high_scores):
    width, height = 320, 480

    frame = 0
    score_moving = 0
    wait_counter = 0

    high_scores = high_scores[:16]

    # Set the initial x position for the text
    x_pos = [width] * len(high_scores)
    x_speed = [5 * (i + 1) for i in range(len(high_scores))]

    # Set the final x position for the text
    final_x_pos = 20

    score_font = ImageFont.truetype("img/kudos/amstrad_cpc464.ttf", 12)
    title_font = ImageFont.truetype("img/kudos/amstrad_cpc464.ttf", 18)
    images = []
    bg = Image.open("img/kudos/wallpaper.jpg").resize((width, height))
    state = "flying in"
    while True:
        # Create a new image
        image = Image.new("RGB", (width, height), (0, 0, 0))
        image.paste(bg, (0, 0))
        draw = ImageDraw.Draw(image)

        draw.text((50, 50), "::: Kudos :::", fill=(255, 255, 255), font=title_font)

        # Draw the high scores
        for i, player_and_score in enumerate(high_scores):
            player, score = player_and_score['User'], player_and_score['kudos']
            score_text = f"{score:> 4} {player}"
            draw.text(
                (x_pos[i] + 1, 101 + i * 20),
                score_text,
                fill=(0, 0, 0),
                font=score_font,
            )
            draw.text(
                (x_pos[i], 100 + i * 20),
                score_text,
                fill=(255, 255, 255),
                font=score_font,
            )

        # Save the image
        images.append(np.array(image))

        frame += 1

        if state == "flying in":
            # Move the x position to the left
            if x_pos[score_moving] - x_speed[score_moving] < final_x_pos:
                x_speed[score_moving] = x_pos[score_moving] - final_x_pos
            if x_pos[score_moving] > final_x_pos:
                x_pos[score_moving] -= x_speed[score_moving]
            else:
                x_speed[score_moving] = 0
                score_moving += 1
            if score_moving == len(high_scores):
                state = "waiting"
                wait_counter = 0
        elif state == "waiting":
            # Do nothing
            wait_counter += 1
            if wait_counter > 50:  # 2 seconds?
                state = "finished"
        elif state == "finished":
            break
    return imageio.imwrite("<bytes>", images, fps=30, extension=".mp4")


def _record_kudos(ctx: ExtendedContext, sender_name, recipient_name, recipient_user_id, reason):
    database_url = os.environ['KUDOS_DATABASE_URL']
    with psycopg.connect(database_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cmd_vars = {
                'sender_name': sender_name, 'sender_id': ctx.chat.user_id,
                'recipient_name': recipient_name, 'recipient_id': recipient_user_id,
                'team_name': ctx.chat.team_name, 'team_id': ctx.chat.team_id,
                'channel_name': ctx.chat.channel_name, 'channel_id': ctx.chat.channel_id,
                'permalink': ctx.message.permalink, 'reason': reason}
            cur.execute(SQL_KUDOS_INSERT, params=cmd_vars)
            success = cur.rowcount > 0
    return success
