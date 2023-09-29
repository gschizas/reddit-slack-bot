import os

import click
import requests

from commands import gyrobot, chat
from state_file import state_file


@gyrobot.command('weather', aliases=['w'])
@click.argument("place", nargs=-1, required=False)
@click.pass_context
def weather(ctx, place):
    """Display the weather in any place.

    Syntax: weather PLACE

    if PLACE is skipped, the location from the last query is used.
    """
    place_full = ' '.join(place)

    with state_file('weather') as pref_cache:
        if place_full:
            pref_cache[chat(ctx).user_id] = place_full
        else:
            place_full = pref_cache.get(chat(ctx).user_id, '')

    if place_full == 'macedonia' or place_full == 'makedonia':
        place_full = 'Thessaloniki'
    if place_full == '':
        chat(ctx).send_text(
            ('You need to first set a default location\n'
             f'Try `{chat(ctx).bot_name} weather LOCATION`'), is_error=True)
        return
    place_full = place_full.replace("?", "")
    if place_full in ('brexit', 'pompeii'):
        title = 'the floor is lava'
        with open('img/weather/lava.png', 'rb') as f:
            file_data = f.read()
    else:
        weather_url = os.environ.get('WEATHER_URL', 'http://wttr.in/')
        weather_page = requests.get(weather_url + place_full + '_p0.png?m')
        file_data = weather_page.content
        title = place_full
    chat(ctx).send_file(file_data, title=title, filetype='png')
