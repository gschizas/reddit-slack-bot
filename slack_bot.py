#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import cmd
import datetime
import io
import json
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

from common import setup_logging
from praw_wrapper import praw_wrapper


def init():
    global r
    global sc
    global subreddit_name
    slack_api_token = os.environ['SLACK_API_TOKEN']
    subreddit_name = os.environ.get('SUBREDDIT_NAME')
    sc = SlackClient(slack_api_token)
    r = praw_wrapper()


def excepthook(type_, value, tb):
    global shell
    global logger
    try:
        logger.fatal(type_, value, tb, exc_info=True)
        if shell:
            shell._send_text('```\n:::Error:::\n{0!r}```\n'.format(value), is_error=True)
    except:
        sys.__excepthook__(type_, value, tb)


def main():
    global logger, subreddit_name, trigger_word
    logger = setup_logging(os.environ.get('LOG_NAME', 'unknown'))
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
    shell.trigger_word = os.environ['BOT_NAME']

    while True:
        try:
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

                if text.lower().startswith(shell.trigger_word):
                    line = ' '.join(text.lower().split()[1:])
                    shell.channel_id = channel_id
                    shell.team_id = team_id
                    line = shell.precmd(line)
                    stop = shell.onecmd(line)
                    stop = shell.postcmd(stop, line)
                    if stop:
                        sys.exit()
            time.sleep(1)
        except Exception as ex:
            logging.critical(ex)


def process_command(sr, text):
    global r, sc
    args = text.lower().split()[1:]

    if args[0:2] == ['modqueue', 'post']:
        return do_modqueue_posts(sr), None
    elif len(args) == 2 and args[0:1] == ['usernotes']:
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
                    username=self.trigger_word)

    def _send_image(self, file_data):
        sc.api_call("files.upload",
                    channels=self.channel_id,
                    icon_emoji=':robot_face:',
                    username=self.trigger_word,
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
        self._send_text(
            f"```I don't know what to do with {line}.{chr(10)}I can understand the following commands:\n```",
            is_error=True)
        self.do_help('')

    def do_crypto(self, arg):
        """Display the current exchange rate of currency"""
        cryptocoin = arg.strip().upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            self._send_text('```' + prices['Message'] + '```\n', is_error=True)
        else:
            self._send_text(f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}")

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
        arg_parts = arg.split()
        if len(arg_parts) != 4:
            self._send_text(f"Argument count error.")
            return

        value_text, currency_from, _, currency_to = arg_parts

        try:
            value = float(value_text)
        except ValueError:
            self._send_text(f"{value_text} is not a good number")
            return

        if not (re.match(r'^\w+$', currency_from)):
            self._send_text(f"{currency_from} is not a real currency")
            return

        if not (re.match(r'^\w+$', currency_to)):
            self._send_text(f"{currency_to} is not a real currency")
            return

        currency_from = currency_from.upper()
        currency_to = currency_to.upper()

        if currency_from == currency_to:
            self._send_text("Tautological bot is tautological")
            return

        prices_page = requests.get("https://min-api.cryptocompare.com/data/price",
                                   params={'fsym': currency_from, 'tsyms': currency_to})
        logger.info(prices_page.url)
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
        redditor_username = arg.strip()
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

    def do_modqueue_comments(self, arg):
        """Display comments from the modqueue"""
        text = ''
        for c in self.sr.mod.modqueue(only='comments', limit=25):
            text += s.content + '\n'
        self._send_text(text)

    def do_youtube_info(self, arg):
        """Get YouTube media URL"""
        global r, logger
        logger.debug(arg)
        post = r.submission(url=arg[1:-1])
        post._fetch()
        if 'media' not in post.__dict__:
            self._send_text('Not a YouTube post', is_error=True)
        try:
            author_url = post.media['oembed']['author_url']
            self._send_text(author_url)
        except Exception as e:
            self._send_text(repr(e), is_error=True)

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

    def do_nuke_thread(self, thread_id):
        """Nuke whole thread (except distinguished comments)
        Thread ID should be either the submission URL or the submission id"""
        if '/' in thread_id:
            if thread_id.startswith('http://') or thread_id.startswith('https://'):
                thread_id = thread_id.split('/')[6]
            elif thread_id.startswith('/'):
                thread_id = thread_id.split('/')[4]
            else:
                thread_id = thread_id.split('/')[3]
        post = r.submission(thread_id)
        post.comments.replace_more(limit=None)
        comments = post.comments.list()
        post.mod.remove()
        for comment in comments:
            if comment.distinguished:
                continue
            if comment.banned_by:
                continue
            comment.mod.remove()
        post.mod.lock()


    @staticmethod
    def _archive_page(url):
        ARCHIVE_URL = 'http://archive.is'
        USER_AGENT = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_0) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/69.0.3497.100 Safari/537.36')
        #PROXY = 'http://45.250.226.14:8080'

        url = url.replace('//www.reddit.com/', '//old.reddit.com/')

        # start_page = requests.get(ARCHIVE_URL)
        # soup = BeautifulSoup(start_page.text, 'lxml')
        # main_form = soup.find('form', {'id': 'submiturl'})
        # submit_id = main_form.find('input', {'name': 'submitid'})['value']
        p2 = requests.post(
            f'{ARCHIVE_URL}/submit/',
            data={
                'url': url
            },
            headers={
                'Referer': 'http://archive.is',
                'User-Agent': USER_AGENT})
            # proxies={'http': PROXY, 'https': PROXY})
        if p2.url == f'{ARCHIVE_URL}/submit/':
            return p2.headers['Refresh'][6:]
        else:
            return p2.url

    def do_archive_user(self, arg):
        """\
        Archive all posts and comments of a user. This helps preserving the
        account history when nuking the user's contribution (especially when
        the user then deletes their account).
        Only one argument, the username"""
        username, *rest_of_text = arg.split()
        if not re.match('[a-zA-Z-_]+', username):
            self._send_text(f'{username} is not a valid username', is_error=True)
            return
        user = r.redditor(username)

        urls_to_archive = []
        urls_to_archive.append(f'{r.config.reddit_url}/user/{user.name}/submitted/')

        submissions = list(user.submissions.new(limit=None))
        for s in submissions:
            urls_to_archive.append(r.config.reddit_url + s.permalink)

        comments = list(user.comments.new(limit=None))
        url_base = f'{r.config.reddit_url}/user/{user.name}/comments?sort=new'
        urls_to_archive.append(url_base)
        for c in comments[24::25]:
            after = c.name
            url = url_base + '&count=25&after=' + after
            urls_to_archive.append(url)
        self._send_text('\n'.join(urls_to_archive))
        final_urls = [self._archive_page(url) for url in urls_to_archive]
        self._send_text('\n'.join(final_urls))


    def do_nuke_user(self, arg):
        """Nuke the comments of a user. Append the timeframe to search.
        Accepted values are 24 (default), 48, 72, A_MONTH, FOREVER_AND_EVER"""
        global r
        global sc
        global subreddit_name
        CUTOFF_AGES = {'24': 1, '48': 2, 'A_MONTH': 30, 'FOREVER_AND_EVER': 36525}
        # FOREVER_AND_EVER is 100 years. Should be enough.

        username, *rest_of_text = arg.split()
        if rest_of_text:
            timeframe = rest_of_text[0].upper()
        else:
            timeframe = '24'
        if timeframe not in CUTOFF_AGES:
            self._send_text(f'{timeframe} is not an acceptable timeframe', is_error=True)
            return
        if not re.match('[a-zA-Z-_]+', username):
            self._send_text(f'{username} is not a valid username', is_error=True)
            return
        u = r.redditor(username)
        all_comments = u.comments.new(limit=None)
        removed_comments = 0
        other_subreddits = 0
        already_removed = 0
        too_old = 0
        other_subreddit_history = {}
        cutoff_age = CUTOFF_AGES[timeframe]
        now = datetime.datetime.utcnow()

        for c in all_comments:
            comment_subreddit_name = c.subreddit.display_name.lower()
            if comment_subreddit_name != subreddit_name:
                other_subreddits += 1
                other_subreddit_history[comment_subreddit_name] = other_subreddit_history.get(comment_subreddit_name, 0) + 1
                continue
            if c.banned_by and c.banned_by != 'AutoModerator':
                already_removed += 1
                continue
            comment_created = datetime.datetime.fromtimestamp(c.created_utc)
            comment_age = now - comment_created
            if comment_age.days > cutoff_age:
                too_old += 1
                continue
            c.mod.remove()
            removed_comments += 1
        result = (
            f"Removed {removed_comments} comments.\n"
            f"{other_subreddits} comments in other subreddits.\n"
            f"{already_removed} comments were already removed.\n"
            f"{too_old} comments were too old for the {timeframe} timeframe.\n"
        )
        self._send_text(result)




if __name__ == '__main__':
    main()
