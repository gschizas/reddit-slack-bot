#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import cmd
import datetime
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import zlib

import prawcore
import requests
import slackclient
from tabulate import tabulate

from common import setup_logging
from praw_wrapper import praw_wrapper


def init():
    global r
    global sc
    global subreddit_name
    slack_api_token = os.environ['SLACK_API_TOKEN']
    subreddit_name = os.environ.get('SUBREDDIT_NAME')
    sc = slackclient.SlackClient(slack_api_token)
    user_agent = f'python:gr.terrasoft.reddit.slackmodbot-{subreddit_name}:v0.1 (by /u/gschizas)'
    r = praw_wrapper(user_agent=user_agent, scopes=['*'])


def excepthook(type_, value, tb):
    global shell
    global logger
    try:
        logger.fatal(type_, value, tb, exc_info=True)
        if shell:
            try:
                error_text = f"```\n:::Error:::\n{value!r}```\n"
            except Exception:
                error_text = "???"
            shell._send_text(error_text, is_error=True)
    except:
        sys.__excepthook__(type_, value, tb)


def main():
    global logger, subreddit_name, trigger_word, shell, teams
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
    logger.debug(f"Listening for {shell.trigger_word}")

    while True:
        try:
            for msg in sc.rtm_read():
                handle_message(msg)
            time.sleep(0.5)
        except Exception as ex: #slackclient.server.SlackConnectionResetError as ex:
            logger.warning(f"{ex}")
            if sc.rtm_connect():
                logger.info("Connection established")
            else:
                logger.critical("Connection failed. Waiting 5 seconds")
                time.sleep(5)


def handle_message(msg):
    global shell, sc, logger, teams
    if msg['type'] != 'message':
        logger.debug(f"Found message of type {msg['type']}")
        return
    if msg.get('subtype') in ('message_deleted', 'file_share', 'bot_message'):
        logger.debug(f"Found message of subtype {msg.get('subtype')}")
        return
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
        logger.debug(f"Triggerred by {text}")
        line = ' '.join(text.split()[1:])
        shell.channel_id = channel_id
        shell.team_id = team_id
        shell.message = msg
        line = shell.precmd(line)
        stop = shell.onecmd(line)
        stop = shell.postcmd(stop, line)
        if stop:
            sys.exit()


class SlackbotShell(cmd.Cmd):
    def __init__(self, **kwargs):
        super().__init__(self, stdout=io.StringIO(), **kwargs)
        self.trigger_word = None
        self.channel_id = None
        self.sr = None
        self.pos = 0

    def _send_text(self, text, is_error=False):
        icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        sc.api_call("chat.postMessage",
                    channel=self.channel_id,
                    text=text,
                    icon_emoji=icon_emoji,
                    username=self.trigger_word)

    def _send_file(self, file_data):
        sc.api_call("files.upload",
                    channels=self.channel_id,
                    icon_emoji=':robot_face:',
                    username=self.trigger_word,
                    file=file_data)

    def _send_fields(self, text, fields):
        sc.api_call("chat.postMessage",
                    channel=self.channel_id,
                    icon_emoji=':robot_face:',
                    text=text,
                    username=self.trigger_word,
                    attachments=fields)

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
        self._send_file(weather.content)

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
        args = arg.strip().split()
        if len(args) not in (1, 2):
            self._send_text(f"Incorrect number of arguments. Either username or username short|long", is_error=True)
        redditor_username = args[0]
        verbose = args[1] if len(args) == 2 else ''
        if verbose.lower() not in ('short', 'long'):
            verbose = ''
        tb_notes = self.sr.wiki['usernotes']
        tb_notes_1 = json.loads(tb_notes.content_md)
        warnings = tb_notes_1['constants']['warnings']
        tb_notes_2 = json.loads(zlib.decompress(base64.b64decode(tb_notes_1['blob'])).decode())
        tb_config = json.loads(self.sr.wiki['toolbox'].content_md)
        usernote_colors = {c['key']: c for c in tb_config['usernoteColors']}
        redditor = r.redditor(redditor_username)
        try:
            redditor._fetch()
            redditor_username = redditor.name  # fix capitalization
            notes = tb_notes_2.get(redditor_username)
            text = ''
            if notes is None:
                self._send_text(f"user {redditor_username} doesn't have any user notes")
                return

            text = ''
            fields = []
            for note in notes['ns']:
                warning = warnings[note['w']]
                when = datetime.datetime.fromtimestamp(note['t'])
                note_text = note['n']
                color = usernote_colors.get(warning, {'color': '#000000'})['color']
                warning_text = usernote_colors.get(warning, {'text': '?' + warning})['text']
                # breakpoint()
                link_parts = note['l'].split(',')
                link_href = '???'
                if link_parts[0] == 'l':
                    if len(link_parts) == 2:
                        link_href = f'{r.config.reddit_url}/r/{self.sr.display_name}/comments/{link_parts[1]}'
                    elif len(link_parts) == 3:
                        link_href = f'{r.config.reddit_url}/r/{self.sr.display_name}/comments/{link_parts[1]}/-/{link_parts[2]}'
                else:
                    link_href = note['l']
                mod_name = tb_notes_1['constants']['users'][note['m']]
                if verbose == 'short':
                    fields.append({
                        'color': color,
                        'text': f"<!date^{int(when.timestamp())}^{{date_short}}|{when.isoformat()}>: {note_text}\n"
                    })
                elif verbose == 'long':
                    fields.append({
                        'color': color,
                        'text': (f"{warning_text} at <!date^{int(when.timestamp())}^{{date_short}} {{time}}|{when.isoformat()}>:"
                                 f"`{note_text}` for <{link_href}> by {mod_name}\n")
                    })
                else:
                    fields.append({
                        'color': color,
                        'text': f"{warning_text} at <!date^{int(when.timestamp())}^{{date_short}} {{time}}|{when.isoformat()}>: `{note_text}`\n"
                    })
            self._send_fields(text, fields)
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
        for c in self.sr.mod.modqueue(only='comments', limit=10):
            text += r.config.reddit_url + c.permalink + '\n```\n' + c.body[:80] + '\n```\n'
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


    def do_add_policy(self, title):
        """Add a minor policy change done via Slack's #modpolicy channel"""
        global r, subreddit_name
        permalink_response = sc.api_call('chat.getPermalink',
                    channel=self.channel_id,
                    message_ts=self.message['ts'])
        permalink = permalink_response['permalink']
        policy_subreddit = os.environ.get('REDDIT_POLICY_SUBREDDIT', subreddit_name)
        policy_page = os.environ.get('REDDIT_POLICY_PAGE', 'mod_policy_votes')
        sr = r.subreddit(policy_subreddit)
        existing_page = sr.wiki[policy_page]
        content = existing_page.content_md
        today_text = datetime.datetime.strftime(datetime.datetime.utcnow(), '%d/%m/%Y')
        title = re.sub(r'\s', ' ', title)
        title = title.replace('|', '\xa6')
        new_content = f'\r\n{today_text}|{title}|[Slack]({permalink})'
        content = content.strip() + new_content
        existing_page.edit(content)
        self._send_text(f"Policy recorded: `{new_content.strip()}`")


    def do_cointoss(self, args):
        """Toss a coin"""
        toss = random.randrange(2)
        toss_text = ['Heads', 'Tails'][toss]
        self._send_text(toss_text)


    def do_roll(self, arg):
        """Roll a dice. Optional sides argument (e.g. roll 1d20+5, roll 1d6+2, d20 etc.)"""
        sides = 6
        times = 1
        add = 0
        args = arg.split()
        if len(args) > 0:
            dice_spec = re.match('^(?P<Times>\d)d(?P<Sides>\d{1,2})(?:\+(?P<Add>\d))?$', args[0])
            if dice_spec:
                if dice_spec.group('Times'):
                    times = int(dice_spec.group('Times'))
                if dice_spec.group('Add'):
                    add = int(dice_spec.group('Add'))
                if dice_spec.group('Sides'):
                    sides = int(dice_spec.group('Sides'))
        if sides < 2: sides = 6
        if times < 1: times = 1
        rolls = []
        for roll_index in range(times):
            rolls.append(random.randrange(sides))
        final_roll = sum(rolls) + add
        roll_text = ', '.join(map(str, rolls))
        times_text = 'time' if times == 1 else 'times'
        self._send_text(f"You rolled a {sides}-sided dice {times} {times_text} with a bonus of +{add}. You got {roll_text}. Final roll: *{final_roll}*")

    def do_survey(self, arg):
        """Get results from survey"""
        if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ:
            self._send_text('No questionnaire found', error=True)
            return
        if 'QUESTIONNAIRE_FILE' not in os.environ:
            self._send_text('No questionnaire file found', error=True)
            return
        import psycopg2
        DATABASE_URL = os.environ['QUESTIONNAIRE_DATABASE_URL']
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        queries = {
            'count': {'result': 'single', 'query': 'SELECT COUNT(*) FROM "Votes"'},
            'mods': {'result': 'table', 'query': """\
select code, answer_value, 
    case answer_value
         when 'A000' then 'gschizas'
         when 'A001' then 'SaltySolomon'
         when 'A002' then 'robbit42'
         when 'A003' then 'zurfer75'
         when 'A004' then 'Greekball'
         when 'A005' then 'aalp234'
         when 'A006' then 'MarktpLatz'
         when 'A007' then 'rEvolutionTU'
         when 'A008' then 'HugodeGroot'
         when 'A009' then 'MarlinMr'
         when 'A010' then 'BkkGrl'
         when 'A011' then 'H0agh'
         when 'A013' then 'SlyScorpion'
         when 'A014' then 'Tetizeraz'
         when 'A016' then 'Blackfire853'
         when 'A017' then 'MariMada'
         when 'A018' then 'RifleSoldier'
         when 'A019' then 'svaroz1c'
         when 'A020' then 'EtKEnn'
         when 'A021' then 'jtalin'
         when 'A022' then 'kinmix'
         when 'A023' then 'Sejani'
         when 'A024' then 'Mortum1'
         when 'A025' then 'Paxan' end as moderator,
       count(*)
from "Answers"
where code like 'q\_60'
group by code, answer_value
order by 4 desc"""}
        }
        query_info = queries.get(arg)
        if not query_info:
            self._send_text(f"You need to specify a query from {','.join(list(queries.keys()))}")
            return
        sql = query_info['query']
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result_type = query_info['result']
        if result_type == 'single':
            self._send_text(f"*Result*: `{rows[0][0]}`")
        elif result_type == 'table':
            cols = [col.name for col in cur.description]
            table = tabulate(rows, headers=cols, tablefmt='pipe')
            self._send_file(table)


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
        if not re.match('[a-zA-Z0-9_-]+', username):
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
        """\
        Nuke the comments of a user. Append the timeframe to search.
        Accepted values are 24 (default), 48, 72, A_MONTH, FOREVER_AND_EVER"""
        global r
        global sc
        global subreddit_name
        CUTOFF_AGES = {'24': 1, '48': 2, '72': 3, 'A_MONTH': 30, 'FOREVER_AND_EVER': 36525}
        # FOREVER_AND_EVER is 100 years. Should be enough.

        username, *rest_of_text = arg.split()
        if rest_of_text:
            timeframe = rest_of_text[0].upper()
        else:
            timeframe = '24'
        if timeframe not in CUTOFF_AGES:
            self._send_text(f'{timeframe} is not an acceptable timeframe', is_error=True)
            return
        if not re.match('[a-zA-Z0-9_-]+', username):
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

    def do_binary(self, arg):
        """Convert binary to text"""
        rest_of_text = ' '.join(arg.split())
        try:
            decoded_text = ''.join([chr(int(c, 2)) for c in rest_of_text.split()])
        except Exception as e:
            decoded_text = str(e)
        self._send_text('\n'.join(decoded_text))

    do_bin = do_binary


if __name__ == '__main__':
    main()
