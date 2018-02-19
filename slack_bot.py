#!/usr/bin/env python3.6
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

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    fh = logging.handlers.TimedRotatingFileHandler('logs/slack_bot.log', when='midnight')
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
    global subreddit_teams
    slack_api_token = os.environ['SLACK_API_TOKEN']
    sc = SlackClient(slack_api_token)
    r = praw_wrapper()
    subreddit_teams = {
        'reddit-europe': 'europe',
        'reddit-greece': 'greece'
    }


def main():
    global logger
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
            if msg.get('subtype') == 'message_changed':
                msg.update(msg['message'])
                del msg['message']

            channel_id = msg['channel']
            team_id = msg.get('source_team', '')

            response = sc.api_call('team.info')
            if response['ok']:
                teams[team_id] = response['team']

            teaminfo = teams.get(team_id, {'name': 'Unknown - ' + team_id, 'domain': ''})

            text = msg['text']

            if text.lower().startswith('eurobot'):
                subreddit_name = subreddit_teams.get(teaminfo['domain'])
                if not subreddit_name:
                    continue
                sr = r.subreddit(subreddit_name)
                reply_text = process_command(sr, text)
                if reply_text:
                    sc.api_call("chat.postMessage", channel=channel_id, text=reply_text)
        time.sleep(1)


def process_command(sr, text):
    global r, sc
    args = text.lower().split()[1:]

    if args[0:2] == ['modqueue', 'post']:
        return cmd_modqueue_posts(sr)
    elif args[0:1] == ['usernotes'] and len(args) == 2:
        return cmd_usernotes(sr, args)
    elif len(args) == 2 and args[0] == 'crypto':
        return cmd_crypto_price(args)
    elif args[0:1] == ['fortune']:
        return cmd_fortune()
    elif args[0:2] == ['domaintag', 'add'] and len(args) == 4:
        return cmd_add_domain_tag(sr, args[2], args[3])
    else:
        return None


def cmd_crypto_price(args):
    cryptocoin = args[1].upper()
    prices = requests.get("https://min-api.cryptocompare.com/data/price",
                          params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
    if prices.get('Response') == 'Error':
        text = prices['Message']
    else:
        text = f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}"
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
