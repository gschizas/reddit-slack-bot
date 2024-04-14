import collections
import ctypes
import datetime
import json
import math
import os
import re
import subprocess

import click
import humanfriendly
import psutil
import requests
import unicodedata

from commands import gyrobot
from commands.extended_context import ExtendedContext

_ntuple_diskusage = collections.namedtuple('usage', 'total used free')


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


@gyrobot.command('covid', aliases=['covid19', 'covid_19'],
                 context_settings={
                     'ignore_unknown_options': True,
                     'allow_extra_args': True})
@click.argument('country', type=click.STRING)
@click.pass_context
def covid(ctx: ExtendedContext, country: str):
    """Display last available statistics for COVID-19 cases

    Syntax:

    covid19 GR
    covid19 GRC
    covid19 Greece
    covid19 Ελλάδα"""

    def _lookup_country(a_country):
        a_country = a_country.lower()
        a_country = {'uk': 'gb'}.get(a_country, a_country)
        with open('countries.json') as f:
            country_lookup = json.load(f)
        # if a_country == 'usa': search_country = 'us'

        found_countries = [c for c in country_lookup
                           if a_country == c['name']['common'].lower()
                           or a_country == c['name']['official'].lower()
                           or any([a_country == names['common'].lower() for lang, names in c['name']['native'].items()])
                           or any(
                [a_country == names['official'].lower() for lang, names in c['name']['native'].items()])
                           or a_country == c['cca2'].lower()
                           or a_country == c['cca3'].lower()
                           or a_country == c['cioc'].lower()]
        result = found_countries[0] if len(found_countries) > 0 else None
        return result

    if country == '19' and len(ctx.args):
        country = ctx.args.pop(0)
    if len(ctx.args) > 0:
        country += ' ' + ' '.join(ctx.args)
    country_info = _lookup_country(country.lower())
    if not country_info:
        ctx.chat.send_text(f"Country \"{country}\" not found", is_error=True)
        return
    country = country_info['cca3'].upper()

    with open('data/owid-covid-data.json') as f:
        full_data = json.load(f)
        if isinstance(full_data, str):
            full_data = json.loads(full_data)
    country_data = full_data[country]
    data = {}
    relevant_data = list(filter(lambda d: ('new_cases' in d and 'new_deaths' in d), country_data['data']))
    for data_for_day in relevant_data[-7:-1]:
        data |= data_for_day
        if 'new_vaccinations' or 'total_vaccinations' in data_for_day:
            data['vaccinations_on'] = data_for_day['date']

    report_date = datetime.datetime.strptime(data['date'], '%Y-%m-%d')

    new_cases = data.get('new_cases', 0.0)
    new_deaths = data.get('new_deaths', 0.0)
    new_vaccinations = data.get('new_vaccinations', 0.0)
    total_vaccinations = data.get('total_vaccinations', 0.0)
    vaccinations_percent = data.get('total_vaccinations_per_hundred', 0.0)
    vaccinations_on = datetime.datetime.strptime(data['vaccinations_on'], '%Y-%m-%d')
    ctx.chat.send_text((f"*Date*: {report_date:%h %d %Y}\n"
                        f"*New Cases*: {new_cases:.10n}\n"
                        f"*Deaths*: {new_deaths:.10n}\n"
                        f"*Vaccinations*: {new_vaccinations:.10n}/{total_vaccinations:.10n} "
                        f"({vaccinations_percent:.5n}%) - on {vaccinations_on:%h %d %Y}"))


@gyrobot.command('crypto')
@click.argument('symbol', nargs=-1)
@click.pass_context
def crypto(ctx: ExtendedContext, symbol):
    """Display the current exchange rate of currency"""
    for cryptocoin in symbol:
        cryptocoin = cryptocoin.upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            ctx.chat.send_text('```' + prices['Message'] + '```\n', is_error=True)
        else:
            ctx.chat.send_text(f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}")


def _diskfree():
    du = _disk_usage_raw('/')
    du_text = _disk_usage_human()
    return _progress_bar(du.used / du.total, 48) + '\n```\n' + du_text + '\n```\n'


if hasattr(os, 'statvfs'):  # POSIX
    def _disk_usage_raw(path):
        st = os.statvfs(path)
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return _ntuple_diskusage(total, used, free)


    def _disk_usage_human():
        disk_usage_command = [
            'df',
            '--total',
            '--exclude-type=tmpfs',
            '--exclude-type=devtmpfs',
            '--exclude-type=squashfs',
            '--human-readable']
        return subprocess.check_output(disk_usage_command).decode()

elif os.name == 'nt':  # Windows
    def _disk_usage_raw(path):
        _, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), \
            ctypes.c_ulonglong()
        fun = ctypes.windll.kernel32.GetDiskFreeSpaceExW
        ret = fun(path, ctypes.byref(_), ctypes.byref(total), ctypes.byref(free))
        if ret == 0:
            raise ctypes.WinError()
        used = total.value - free.value
        return _ntuple_diskusage(total.value, used, free.value)


    def _disk_usage_human():
        disk_usage_command = ['wmic', 'LogicalDisk', 'Where DriveType="3"', 'Get', 'DeviceID,FreeSpace,Size']
        return subprocess.check_output(disk_usage_command).decode()


def _progress_bar(percentage, size):
    filled = math.ceil(size * percentage)
    empty = math.floor(size * (1 - percentage))
    bar = '\u2588' * filled + '\u2591' * empty
    return bar


@gyrobot.command('disk_space')
@click.pass_context
def disk_space(ctx: ExtendedContext):
    """\
    Display free disk space"""
    ctx.chat.send_text(_diskfree())


@gyrobot.command('disk_space_ex')
@click.pass_context
def disk_space_ex(ctx):
    """Display free disk space"""
    ctx.chat.send_text('```' + subprocess.check_output(
        ['duf',
         '-only', 'local',
         '-output', 'mountpoint,size,avail,usage',
         '-style', 'unicode',
         '-width', '120']).decode() + '```')


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


MID_DOT: str = '\xb7'

EMPTY_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="


@gyrobot.command('stocks', aliases=['stock', 'stonk'])
@click.argument("stock_name")
@click.pass_context
def stocks(ctx: ExtendedContext, stock_name):
    """Show info for a stock"""
    import yfinance as yf

    if '|' in stock_name:
        stock_name = re.findall(r'\|(.*)>', stock_name)[0]
    stock_name = stock_name.replace(MID_DOT, '.')
    stock = yf.Ticker(stock_name)

    change = (((stock.info['ask'] / stock.info['previousClose']) - 1) * 100)  # > 10

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{stock.info['longName']} ({stock.info['symbol'].replace('.', MID_DOT)}) " +
                        f"{stock.info['currency']}"
            },
            "accessory": {
                "type": "image",
                "image_url": stock.info.get('logo_url', EMPTY_IMAGE),
                "alt_text": stock.info['longName']
            },
            "fields": [
                {
                    "type": "plain_text",
                    "text": f"Ask Price: {stock.info['ask']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Bid: {stock.info['bid']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Low: {stock.info['regularMarketDayLow']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Day High: {stock.info['dayHigh']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Last Day: {stock.info['regularMarketPreviousClose']}"
                },
                {
                    "type": "plain_text",
                    "text": f"Change: {change:.02f}"
                }
            ]
        }
    ]
    ctx.chat.send_blocks(blocks)


@gyrobot.command('uptime')
@click.pass_context
def uptime(ctx):
    """Show uptime"""
    now = datetime.datetime.now()
    server_uptime = now - datetime.datetime.fromtimestamp(psutil.boot_time())
    process_uptime = now - datetime.datetime.fromtimestamp(psutil.Process(os.getpid()).create_time())
    ctx.chat.send_text((f"Server uptime: {humanfriendly.format_timespan(server_uptime)}\n"
                        f"Process uptime: {humanfriendly.format_timespan(process_uptime)}"))


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


@gyrobot.command('unicode')
@click.argument('text', nargs=-1)
@click.pass_context
def unicode(ctx: ExtendedContext, text):
    """Convert text to unicode code points"""
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
