#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import datetime
import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import time
import urllib.parse
import zlib

import prawcore
import requests
from slackclient import SlackClient

from praw_wrapper import praw_wrapper


def setup_logging():
    global logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    log_name = os.environ['LOG_NAME']

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    fh = logging.handlers.TimedRotatingFileHandler(f'logs/slack_bot-{log_name}.log', when='midnight')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)


def init():
    global r
    global sc
    global trigger_word
    global subreddit_name
    slack_api_token = os.environ['SLACK_API_TOKEN']
    trigger_word = os.environ['BOT_NAME']
    subreddit_name = os.environ.get('SUBREDDIT_NAME')
    sc = SlackClient(slack_api_token)
    r = praw_wrapper()


def main():
    global logger, subreddit_name, trigger_word
    setup_logging()
    init()

    if sc.rtm_connect():
        logger.info('Connection established')
    else:
        logger.critical('Connection failed')
        sys.exit(1)

    teams = {}

    while True:
        for msg in sc.rtm_read():
            if msg['type'] != 'message':
                continue
            if msg.get('subtype') in ('message_deleted', 'file_share', 'bot_message'):
                continue
            if 'message' in msg:
                msg.update(msg['message'])
                del msg['message']

            channel_id = msg['channel']
            team_id = msg.get('source_team', '')

            response = sc.api_call('team.info')
            if response['ok']:
                teams[team_id] = response['team']

            teaminfo = teams.get(team_id, {'name': 'Unknown - ' + team_id, 'domain': ''})

            text = msg['text']

            if text.lower().startswith(trigger_word):
                if subreddit_name:
                    sr = r.subreddit(subreddit_name)
                else:
                    sr = None
                reply_text, extra_data = process_command(sr, text)
                if reply_text:
                    if extra_data and 'image' in extra_data:
                        result = sc.api_call("files.upload", channels=channel_id, file=extra_data['image'])
                        logger.info(result)
                    else:
                        sc.api_call("chat.postMessage", channel=channel_id, text=reply_text)
        time.sleep(1)


def process_command(sr, text):
    global r, sc
    args = text.lower().split()[1:]

    if args[0:2] == ['modqueue', 'post']:
        return cmd_modqueue_posts(sr), None
    elif len(args) == 2 and args[0:1] == ['usernotes'] :
        return cmd_usernotes(sr, args), None
    elif len(args) == 2 and args[0] == 'crypto':
        return cmd_crypto_price(args), None
    elif args[0:1] == ['fortune']:
        return cmd_fortune(), None
    elif args[0:2] == ['domaintag', 'add'] and len(args) == 4:
        return cmd_add_domain_tag(sr, args[2], args[3]), None
    elif len(args) == 4 and args[2] == 'in':
        return cmd_do_conversion(args[0], args[1], args[3]), None
    elif len(args) >= 2 and args[0:1] in [['w'], ['weather']]:
        return cmd_weather(' '.join(args[1:]))
    elif len(args) >= 2 and args[0:1] in [['you'], ['your'], ['youre'], ["you're"]]:
        return "No, you're " + ' '.join(args[1:]), None
    else:
        logger.info(args)
        return None, None


def cmd_crypto_price(args):
    cryptocoin = args[1].upper()
    prices = requests.get("https://min-api.cryptocompare.com/data/price",
                          params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
    if prices.get('Response') == 'Error':
        text = prices['Message']
    else:
        text = f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}"
    return text


def cmd_weather(place):
    weather = requests.get('http://wttr.in/' + place + '_p0.png')
    return weather.ok, {'image': weather.content}


def cmd_do_conversion(value_text, currency_from, currency_to):
    try:
        value = float(value_text)
    except ValueError:
        return f"{value_text} is not a good number"

    if not(re.match('^\w+$', currency_from)):
        return f"{currency_from} is not a real currency"

    if not(re.match('^\w+$', currency_to)):
        return f"{currency_to} is not a real currency"

    currency_from = currency_from.upper()
    currency_to = currency_to.upper()

    if currency_from == currency_to:
        return "Tautological bot is tautological"

    prices_page = requests.get("https://min-api.cryptocompare.com/data/price",
                          params={'fsym': currency_from, 'tsyms': currency_to})
    logging.info(prices_page.url)
    prices = prices_page.json()
    if prices.get('Response') == 'Error':
        text = prices['Message']
    else:
        price = prices[currency_to]
        new_value = value * price
        text = f"{value:.2f} {currency_from} is {new_value:.2f} {currency_to}"
    return text


def cmd_usernotes(sr, args):
    redditor_username = args[1]
    tb_notes = sr.wiki['usernotes']
    tb_notes_1 = json.loads(tb_notes.content_md)
    warnings = tb_notes_1['constants']['warnings']
    tb_notes_2 = json.loads(zlib.decompress(base64.b64decode(tb_notes_1['blob'])).decode())
    redditor = r.redditor(redditor_username)
    try:
        redditor._fetch()
        redditor_username = redditor.name  # fix capitalization
        notes = tb_notes_2.get(redditor_username)
        text = ''
        if notes is None:
            return f"user {redditor_username} doesn't have any user notes"

        for note in notes['ns']:
            warning = warnings[note['w']]
            when = datetime.datetime.fromtimestamp(note['t'])
            note = note['n']
            text += (f"<!date^{int(when.timestamp())}^{warning} at {{date_short}} {{time}}: {note}|"
                     f"{warning} at {when.isoformat()}: {note}>\n")
        return text
    except prawcore.exceptions.NotFound:
        return f"user {redditor_username} not found"


def cmd_modqueue_posts(sr):
    text = ''
    for s in sr.mod.modqueue(only='submissions'):
        text += s.title + '\n' + s.url + '\n'
    return text


def cmd_fortune():
    return subprocess.check_output('/usr/games/fortune').decode()


def cmd_add_domain_tag(sr, url_text, color):
    toolbox_data = json.loads(sr.wiki['toolbox'].content_md)
    if re.match('<.*>', url_text):
        url_text = url_text[1:-1]
    url = urllib.parse.urlparse(url_text)
    final_url = url.netloc
    if len(url.path) > 1:
        final_url += url.path
    if not re.match(r'\#[0-9a-f]{6}', color, re.IGNORECASE):
        return f"{color} is not a good color on you!"
    entry = [tag for tag in toolbox_data['domainTags'] if tag['name'] == final_url]
    if entry:
        entry['color'] = color
    else:
        toolbox_data['domainTags'].append({'name': final_url, 'color': color})
    sr.wiki['toolbox'].edit(json.dumps(toolbox_data), 'Updated by slackbot')
    return f"Added color {color} for domain {final_url}"


if __name__ == '__main__':
    main()
