import os
import subprocess

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('fortune')
@click.pass_context
def fortune(ctx: ExtendedContext):
    """Like a Chinese fortune cookie, but less yummy"""
    ctx.chat.send_text(subprocess.check_output(['/usr/games/fortune']).decode())


@gyrobot.command('joke')
@click.pass_context
def joke(ctx: ExtendedContext):
    """Tell a joke"""
    proxies = {'http': os.environ['ALT_PROXY'], 'https': os.environ['ALT_PROXY']} if 'ALT_PROXY' in os.environ else {}
    joke_page = requests.get(
        'https://icanhazdadjoke.com/',
        headers={
            'Accept': 'text/plain',
            'User-Agent': 'Slack Bot for Reddit (https://github.com/gschizas/slack-bot)'},
        proxies=proxies)
    joke_text = joke_page.content
    ctx.chat.send_text(joke_text.decode())
