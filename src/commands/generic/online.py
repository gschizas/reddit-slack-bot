import json

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('urban_dictionary', aliases=['ud'])
@click.argument('terms', nargs=-1)
@click.pass_context
def urban_dictionary(ctx: ExtendedContext, terms):
    """Search in urban dictionary for the first definition of the word or phrase"""
    term = ' '.join(terms)
    definition_page = requests.get('http://api.urbandictionary.com/v0/define', params={'term': term})
    definition_answer = definition_page.json()
    if len(definition_answer) > 0:
        ctx.chat.send_text(definition_answer['list'][0]['definition'])
    else:
        ctx.chat.send_text(f"Could not find anything for {term}", is_error=True)


@gyrobot.command('youtube_info')
@click.argument('url')
@click.pass_context
def youtube_info(ctx: ExtendedContext, url):
    if url.startswith('<') and url.endswith('>'):
        url = url[1:-1]
    ctx.logger.info(url)
    youtube_data = requests.get('https://youtube.com/oembed', params={'url': url, 'format': 'json'})
    ctx.logger.debug(youtube_data.text)
    actual_data = json.dumps(json.loads(youtube_data.content), ensure_ascii=False, indent=4).encode()
    ctx.chat.send_file(actual_data, title=youtube_data.json().get('title', '(no title)'))
