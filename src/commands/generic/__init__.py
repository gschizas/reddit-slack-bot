import re
import subprocess

import click
import unicodedata

from commands import gyrobot
from commands.extended_context import ExtendedContext
from backend.constants import TableFormat

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



@gyrobot.command('path')
@click.pass_context
def showpath(ctx: ExtendedContext):
    """Show full environment"""
    import os
    text = os.environ['PATH'].replace(':', '\n')
    ctx.chat.send_file(text.encode('utf8'), filename='env.txt', title='env')



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
def version(ctx: ExtendedContext):
    """Display version"""
    ctx.chat.send_text(f"Version: {_version}")

@gyrobot.command('planets')
@click.option('-f', '--format', type=TableFormat, default=TableFormat.TABLE)
@click.pass_context
def show_planets(ctx: ExtendedContext, table_format: TableFormat=TableFormat.TABLE):
    """Test table"""
    planets = [
        {"name": "Mercury", "diameter_km": 4879, "mass_kg": 3.30e23, "day_hours": 1407.6, "year_days": 88},
        {"name": "Venus", "diameter_km": 12104, "mass_kg": 4.87e24, "day_hours": 5832.5, "year_days": 225},
        {"name": "Earth", "diameter_km": 12742, "mass_kg": 5.97e24, "day_hours": 24, "year_days": 365},
        {"name": "Mars", "diameter_km": 6779, "mass_kg": 6.42e23, "day_hours": 24.6, "year_days": 687},
        {"name": "Jupiter", "diameter_km": 139820, "mass_kg": 1.90e27, "day_hours": 9.9, "year_days": 4333},
        {"name": "Saturn", "diameter_km": 116460, "mass_kg": 5.68e26, "day_hours": 10.7, "year_days": 10759},
        {"name": "Uranus", "diameter_km": 50724, "mass_kg": 8.68e25, "day_hours": 17.2, "year_days": 30687},
        {"name": "Neptune", "diameter_km": 49244, "mass_kg": 1.02e26, "day_hours": 16.1, "year_days": 60190}
    ]
    ctx.chat.send_table(f"Testing {_version}", planets, table_format=table_format)