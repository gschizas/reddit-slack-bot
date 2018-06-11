#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import cmd
import datetime
import io
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

def excepthook(type_, value, tb):
    global shell
    try:
        logger.fatal(type_, value, tb, exc_info=True)
        if shell:
            shell._send_text('```\n:::Error:::\n{0!r}```\n'.format(value), is_error=True)
    except:
        sys.__excepthook__(type_, value, tb)


def main():
    global logger, subreddit_name, trigger_word, shell
    setup_logging()
    sys.excepthook = excepthook
    init()

    if sc.rtm_connect():
        logger.info('Connection established')
    else:
        logger.critical('Connection failed')
        sys.exit(1)

    teams = {}
    shell = SlackbotShell()
    if subreddit_name:
        shell.sr = r.subreddit(subreddit_name)

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
                line = ' '.join(text.lower().split()[1:])
                shell.channel_id = channel_id
                shell.team_id = team_id
                line = shell.precmd(line)
                stop = shell.onecmd(line)
                stop = shell.postcmd(stop, line)
                if stop:
                    sys.exit()
                # reply_text, extra_data = process_command(sr, text)
                # if reply_text:
                #     if extra_data and 'image' in extra_data:
                #         
                #         logger.info(result)
                #     else:
                #         
        time.sleep(1)


def process_command(sr, text):
    global r, sc
    args = text.lower().split()[1:]

    if args[0:2] == ['modqueue', 'post']:
        return do_modqueue_posts(sr), None
    elif len(args) == 2 and args[0:1] == ['usernotes'] :
        return do_usernotes(sr, args), None
    elif len(args) == 2 and args[0] == 'crypto':
        return do_crypto_price(args), None
    elif args[0:1] == ['fortune']:
        return do_fortune(), None
    elif args[0:2] == ['domaintag', 'add'] and len(args) == 4:
        return do_add_domain_tag(sr, args[2], args[3]), None
    elif len(args) == 4 and args[2] == 'in':
        return do_do_conversion(args[0], args[1], args[3]), None
    elif len(args) >= 2 and args[0:1] in [['w'], ['weather']]:
        return do_weather(' '.join(args[1:]))
    elif len(args) >= 2 and args[0:1] in [['you'], ['your'], ['youre'], ["you're"]]:
        """Eurobot is as nice to you as you are to him"""
        return "No, you're " + ' '.join(args[1:]), None
    elif len(args) >= 2 and args[0:1] in [['binary'], ['bin']]:
        """Convert binary to text"""
        rest_of_text = ' '.join(args[1:])
        try:
            decoded_text = ''.join([chr(int(c, 2)) for c in rest_of_text.split()])
        except Exception as e:
            decoded_text = e.message
        return decoded_text, None
    else:
        logger.info(args)
        return None, None

class SlackbotShell(cmd.Cmd):
    def __init__(self, **kwargs):
        super().__init__(self, stdout=io.StringIO(), **kwargs)
        self.sr = None
        self.pos = 0

    def _send_text(self, text, is_error=False):
        icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        sc.api_call("chat.postMessage", 
            channel=self.channel_id,
            text=text,
            icon_emoji=icon_emoji,
            username=trigger_word)

    def _send_image(self, file_data):
        sc.api_call("files.upload",
            channels=self.channel_id,
            file=file_data)

    def postcmd(self, stop, line):
        self.stdout.flush()
        self.stdout.seek(self.pos, io.SEEK_SET)
        text = self.stdout.read()
        self.stdout.close()
        self.stdout = io.StringIO()
        # self.pos = self.stdout.seek(0, io.SEEK_CUR)
        if text != '':
            self._send_text('```\n' + text.strip() + '```\n')
        return stop


    def default(self, line):
        self._send_text(f"```I don't know what to do with {line}.{chr(10)}I can understand the following commands:\n```", is_error=True)
        self.do_help('')


    def do_crypto(self, arg):
        """Display the current exchange rate of currency"""
        args = arg.split()
        cryptocoin = args[1].upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            text = prices['Message']
        else:
            text = f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}"
        self._send_text(text)


    def do_weather(self, arg):
        """Display the weather in place"""
        place = arg.lower()
        if place == 'macedonia' or place == 'makedonia':
            place = 'Thessaloniki'
        weather = requests.get('http://wttr.in/' + place + '_p0.png')
        self._send_image(weather.content)
    do_w = do_weather


    def do_convert(self, arg):
        """Convert money from one currency to another"""
        args = arg.split()
        if len(args) != 3:
            self._send_text(f"Argument count error.")
            return

        value_text, currency_from, currency_to = arg_parts

        try:
            value = float(value_text)
        except ValueError:
            self._send_text(f"{value_text} is not a good number")
            return

        if not(re.match(r'^\w+$', currency_from)):
            self._send_text(f"{currency_from} is not a real currency")
            return

        if not(re.match(r'^\w+$', currency_to)):
            self._send_text(f"{currency_to} is not a real currency")
            return

        currency_from = currency_from.upper()
        currency_to = currency_to.upper()

        if currency_from == currency_to:
            self._send_text("Tautological bot is tautological")
            return

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
        self._send_text(text)


    def do_usernotes(self, arg):
        """Display usernotes of a user"""
        args = arg.split()
        redditor_username = args[1]
        tb_notes = self.sr.wiki['usernotes']
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
                self._send_text(f"user {redditor_username} doesn't have any user notes")
                return

            for note in notes['ns']:
                warning = warnings[note['w']]
                when = datetime.datetime.fromtimestamp(note['t'])
                note = note['n']
                text += (f"<!date^{int(when.timestamp())}^{warning} at {{date_short}} {{time}}: {note}|"
                         f"{warning} at {when.isoformat()}: {note}>\n")
            self._send_text(text)
            return
        except prawcore.exceptions.NotFound:
            self._send_text(f"user {redditor_username} not found")
            return


    def do_modqueue_posts(self, arg):
        """Display posts from the modqueue"""
        text = ''
        for s in self.sr.mod.modqueue(only='submissions'):
            text += s.title + '\n' + s.url + '\n'
        self._send_text(text)


    def do_fortune(self, args):
        """Like a Chinese fortune cookie, but less yummy"""
        self._send_text(subprocess.check_output('/usr/games/fortune').decode())


    def do_add_domain_tag(self, url_text, color):
        """Add a tag to a domain"""
        toolbox_data = json.loads(self.sr.wiki['toolbox'].content_md)
        if re.match('<.*>', url_text):
            url_text = url_text[1:-1]
        url = urllib.parse.urlparse(url_text)
        final_url = url.netloc
        if len(url.path) > 1:
            final_url += url.path
        if not re.match(r'\#[0-9a-f]{6}', color, re.IGNORECASE):
            self._send_text(f"{color} is not a good color on you!")
            return
        entry = [tag for tag in toolbox_data['domainTags'] if tag['name'] == final_url]
        if entry:
            entry['color'] = color
        else:
            toolbox_data['domainTags'].append({'name': final_url, 'color': color})
        self.sr.wiki['toolbox'].edit(json.dumps(toolbox_data), 'Updated by slack')
        self._send_text(f"Added color {color} for domain {final_url}")


if __name__ == '__main__':
    main()
