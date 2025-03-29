import re
import subprocess

import click
import unicodedata

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('binary', aliases=['b'],
                 context_settings={
                     'ignore_unknown_options': True,
                     'allow_extra_args': True}
                 )
@click.pass_context
def binary(ctx):
    """Convert binary to text"""
    rest_of_text = ' '.join(ctx.args)
    rest_of_text = re.sub(r'(\S{8})\s?', r'\1 ', rest_of_text)
    decoded_text = ''.join([chr(int(c, 2)) for c in rest_of_text.split()])
    ctx.chat.send_text(''.join(decoded_text))


@gyrobot.command('unicode')
@click.argument('text', nargs=-1)
@click.pass_context
def unicode(ctx: ExtendedContext, text):
    """Convert text to Unicode code points"""
    text = ' '.join(text)
    final_text = ''
    for char in text:
        final_text += f"U+{ord(char):06x} {char} {unicodedata.name(char)}\n"
    ctx.chat.send_file(final_text.encode('utf8'), filename='UnicodeAnalysis.txt', title='Unicode')


def _get_version():
    git_version_command = [
        'git',
        'describe',
        '--all',
        '--long']
    return subprocess.check_output(git_version_command).decode()


_version = _get_version()


@gyrobot.command('version')
@click.pass_context
def version(ctx):
    """Display version"""
    ctx.chat.send_text(f"Version: {_version}")
