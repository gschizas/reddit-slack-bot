#!/usr/bin/env python3
import base64
import datetime
import json
import os
import sys
import time
import zlib

import prawcore
import requests
from slackclient import SlackClient

from praw_wrapper import praw_wrapper


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
    init()

    if sc.rtm_connect():
        print('Connection established')
    else:
        print('Connection failed')
        sys.exit(1)

    usernames = {}
    teams = {}

    while True:
        for msg in sc.rtm_read():
            print(msg)
            if msg['type'] != 'message':
                continue
            if msg.get('subtype') in ('message_deleted', 'file_share', 'bot_message'):
                continue
            if msg.get('subtype') == 'message_changed':
                msg.update(msg['message'])
                del msg['message']
                print(msg)

            user_id = msg['user']
            channel_id = msg['channel']
            team_id = msg.get('source_team', '')

            if user_id not in usernames:
                response = sc.api_call('users.info', user=user_id)
                if response['ok']:
                    usernames[user_id] = response['user']['name']

            username = usernames.get(user_id, f"Unknown - {user_id}")

            response = sc.api_call('team.info')
            if response['ok']:
                teams[team_id] = response['team']

            teaminfo = teams.get(team_id, {'name': 'Unknown - ' + team_id, 'domain': ''})

            text = msg['text']
            print('{0} says {1}'.format(username, text))
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
    message_text = ' / '.join(args) + ":tada:"
    print(message_text)
    # sc.api_call("chat.postMessage", channel=channel_id, text=message_text)

    if args[0:2] == ['modqueue', 'post']:
        text = ''
        for s in sr.mod.modqueue(only='submissions'):
            text += s.title + '\n' + s.url + '\n'
        return text
    elif args[0:1] == ['usernotes'] and len(args) == 2:
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
                text = f"user {redditor_username} doesn't have any user notes"
            else:
                for note in notes['ns']:
                    warning = warnings[note['w']]
                    when = datetime.datetime.fromtimestamp(note['t'])
                    note = note['n']
                    text += (f"<!date^{int(when.timestamp())}^{warning} at {{date_short}} {{time}}: {note}|"
                             f"{warning} at {when.isoformat()}: {note}>\n")
        except prawcore.exceptions.NotFound:
            text = f"user {redditor_username} not found"
        return text
    elif len(args) == 2 and args[0] == 'crypto':
        cryptocoin = args[1].upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            text = prices['Message']
        else:
            text = f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}"
        return text
    else:
        return None


if __name__ == '__main__':
    main()
