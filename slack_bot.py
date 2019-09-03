#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import cmd
import datetime
import io
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import zlib

import prawcore
import psycopg2
import requests
import slackclient
import xlsxwriter
from tabulate import tabulate

from bot_framework.common import setup_logging
from bot_framework.praw_wrapper import praw_wrapper
from bot_framework.yaml_wrapper import yaml

SQL_SURVEY_PREFILLED_ANSWERS = """select answer[3] AS Code, answer_value as Answer, count(*) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where  code = 'q_{0}' or code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 3 desc"""
SQL_SURVEY_TEXT = """select answer_value as Answer, count(*) AS VoteCount 
from "Answers"
where code = 'q_{0}'
group by 1
order by 2 desc"""
SQL_SURVEY_SCALE_MATRIX = """select answer[3] AS AnswerCode, answer_value AS AnswerValue, count(vote_id) AS VoteCount
from (select regexp_split_to_array(code, '_') AS answer_parts, *
      from "Answers"
      where code like 'q\_{0}\_%') AS dt(answer)
group by 1, 2
order by 1, 3 desc"""
SQL_SURVEY_PARTICIPATION = """select count(*), date(datestamp) from "Votes"
group by date(datestamp)
order by date(datestamp);"""
SQL_KUDOS_INSERT = """\
INSERT INTO kudos (
   from_user, from_user_id,
   to_user, to_user_id,
   team_name, team_id,
   channel_name, channel_id,
   permalink)
VALUES (
   %(sender_name)s, %(sender_id)s,
   %(recipient_name)s, %(recipient_id)s, 
   %(team_name)s, %(team_id)s,
   %(channel_name)s, %(channel_id)s,
   %(permalink)s);
"""
SQL_KUDOS_VIEW = """\
SELECT to_user as "User", COUNT(*) as Kudos
FROM kudos
WHERE DATE_PART('day', NOW() - datestamp) < %(days)s
GROUP BY to_user
ORDER BY 2 DESC;"""


def init():
    global r
    global sc
    global subreddit_name
    slack_api_token = os.environ['SLACK_API_TOKEN']
    subreddit_name = os.environ.get('SUBREDDIT_NAME')
    sc = slackclient.SlackClient(slack_api_token)
    if subreddit_name:
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
    global logger, subreddit_name, shell, teams, users, channels
    logger = setup_logging(os.environ.get('LOG_NAME', 'unknown'))
    sys.excepthook = excepthook
    init()

    if sc.rtm_connect():
        logger.info('Connection established')
    else:
        logger.critical('Connection failed')
        sys.exit(1)

    teams = {}
    users = {}
    channels = {}

    # Disable features according to environment

    if not subreddit_name:
        del SlackbotShell.do_add_domain_tag
        del SlackbotShell.do_add_policy
        del SlackbotShell.do_archive_user
        del SlackbotShell.do_modqueue_comments
        del SlackbotShell.do_modqueue_posts
        del SlackbotShell.do_nuke_thread
        del SlackbotShell.do_nuke_user
        del SlackbotShell.do_usernotes
        del SlackbotShell.do_youtube_info

    if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ or 'QUESTIONNAIRE_FILE' not in os.environ:
        del SlackbotShell.do_survey

    if 'KUDOS_DATABASE_URL' not in os.environ:
        del SlackbotShell.do_kudos

    shell = SlackbotShell()
    if subreddit_name:
        shell.sr = r.subreddit(subreddit_name)
    shell.trigger_words = os.environ['BOT_NAME'].split()
    logger.debug(f"Listening for {','.join(shell.trigger_words)}")

    while True:
        try:
            for msg in sc.rtm_read():
                handle_message(msg)
            time.sleep(0.5)
        except Exception as ex:  # slackclient.server.SlackConnectionResetError as ex:
            exx = sys.exc_info()
            tb = sys.exc_info()[2]
            logger.warning(''.join(traceback.format_exception(None, ex, tb)))
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
    team_id = msg.get('team', '')
    user_id = msg.get('user', '')

    permalink = sc.api_call('chat.getPermalink', channel=channel_id, message_ts=msg['ts'])
    get_team_info(team_id)

    get_user_info(user_id)
    get_channel_info(team_id, channel_id)

    text = msg['text']
    text = re.sub(r'\u043e|\u03bf', 'o', text)
    text = re.sub(r'\u0435', 'e', text)

    typed_text = text.strip().lower().split()
    if not typed_text:
        return
    first_word = typed_text[0]
    if any([first_word == trigger_word for trigger_word in shell.trigger_words]):
        logger.debug(f"Triggerred by {text}")
        line = ' '.join(text.split()[1:])
        shell.channel_id = channel_id
        shell.team_id = team_id
        shell.message = msg
        shell.user_id = user_id
        shell.permalink = permalink
        try:
            line = shell.precmd(line)
            stop = shell.onecmd(line)
            stop = shell.postcmd(stop, line)
            if stop:
                sys.exit()
        except Exception as e:
            if 'DEBUG' in os.environ:
                exception_full_text = ''.join(traceback.format_exception(*sys.exc_info()))
                error_text = f"```\n:::Error:::\n{exception_full_text}```\n"
            else:
                error_text = f"```\n:::Error:::\n{e}```\n"
            shell._send_text(error_text, is_error=True)


def get_user_info(user_id):
    global sc, users
    if user_id not in users:
        response_user = sc.api_call('users.info', user=user_id)
        if response_user['ok']:
            users[user_id] = response_user['user']


def get_team_info(team_id):
    global sc, teams
    if team_id not in teams:
        response_team = sc.api_call('team.info')
        if response_team['ok']:
            teams[team_id] = response_team['team']


def get_channel_info(team_id, channel_id):
    global sc, channels
    if team_id not in channels:
        channels[team_id] = {}
    if channel_id not in channels[team_id]:
        response_channel = sc.api_call('conversations.info', channel=channel_id)
        if response_channel['ok']:
            channel_info = response_channel['channel']
        if channel_info.get('is_group') or channel_info.get('is_channel'):
            priv = '🔒' if channel_info.get('is_private') else '#'
            channels[team_id][channel_id] = priv + channel_info['name_normalized']
        elif channel_info.get('is_im'):
            response_members = sc.api_call('conversations.members', channel=channel_id)
            for user_id in response_members['members']:
                get_user_info(user_id)
            participants = [f"{users[user_id]['real_name']} <{users[user_id]['name']}@{user_id}>" for user_id in
                            response_members['members']]
            channels[team_id][channel_id] = '🧑' + ' '.join(participants)


class SlackbotShell(cmd.Cmd):
    def __init__(self, **kwargs):
        super().__init__(self, stdout=io.StringIO(), **kwargs)
        self.trigger_words = []
        self.channel_id = None
        self.team_id = None
        self.user_id = None
        self.sr = None
        self.pos = 0
        self.permalink = None

    def _send_text(self, text, is_error=False):
        icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        sc.api_call("chat.postMessage",
                    channel=self.channel_id,
                    text=text,
                    icon_emoji=icon_emoji,
                    username=self.trigger_words[0])

    def _send_file(self, file_data, title=None, filename=None, filetype=None):
        sc.api_call("files.upload",
                    channels=self.channel_id,
                    icon_emoji=':robot_face:',
                    username=self.trigger_words[0],
                    file=file_data,
                    filename=filename,
                    title=title,
                    filetype=filetype or 'auto')

    def _send_fields(self, text, fields):
        sc.api_call("chat.postMessage",
                    channel=self.channel_id,
                    icon_emoji=':robot_face:',
                    text=text,
                    username=self.trigger_words[0],
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
        if place in ('brexit', 'pompeii'):
            title = 'the floor is lava'
            with open('img/lava.png', 'rb') as f:
                file_data = f.read()
        else:
            weather = requests.get('http://wttr.in/' + place + '_p0.png')
            file_data = weather.content
            title = arg
        self._send_file(file_data, title=title, filetype='png')

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
                        link_href = (
                            f'{r.config.reddit_url}/r/{self.sr.display_name}/comments/'
                            f'{link_parts[1]}/-/{link_parts[2]}')
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
                        'text': (f"{warning_text} at <!date^{int(when.timestamp())}"
                                 f"^{{date_short}} {{time}}|{when.isoformat()}>:"
                                 f"`{note_text}` for <{link_href}> by {mod_name}\n")
                    })
                else:
                    fields.append({
                        'color': color,
                        'text': (
                            f"{warning_text} at <!date^{int(when.timestamp())}^{{date_short}} {{time}}|"
                            f"{when.isoformat()}>: `{note_text}`\n")
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

    def do_uptime(self, args):
        """Show uptime"""
        self._send_text(subprocess.check_output(['/usr/bin/uptime', '--pretty']).decode())

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
        comments_removed = 0
        comments_distinguished = 0
        comments_already_removed = 0
        for comment in comments:
            if comment.distinguished:
                comments_distinguished += 1
                continue
            if comment.banned_by:
                comments_already_removed += 1
                continue
            comment.mod.remove()
            comments_removed += 1
        post.mod.lock()
        result = (
                f"{comments_removed} comments were removed.\n"
                f"{comments_distinguished} distinguished comments were kept.\n"
                f"{comments_already_removed} comments were already removed.\n"
                "Submission was locked")
        self._send_text(result)

    def do_add_policy(self, title):
        """Add a minor policy change done via Slack's #modpolicy channel"""
        global r, subreddit_name
        permalink_response = sc.api_call(
            'chat.getPermalink',
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
        self._send_text((
            f"You rolled a {sides}-sided dice {times} {times_text} with a bonus of +{add}."
            f" You got {roll_text}. Final roll: *{final_roll}*"))

    def do_survey(self, arg):
        """Get results from survey"""
        if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ:
            self._send_text('No questionnaire found', is_error=True)
            return
        if 'QUESTIONNAIRE_FILE' not in os.environ:
            self._send_text('No questionnaire file defined', is_error=True)
            return
        questionnaire_file = pathlib.Path('data') / os.environ['QUESTIONNAIRE_FILE']
        if not questionnaire_file.exists():
            self._send_text('No questionnaire file found', is_error=True)
            return
        with questionnaire_file.open(encoding='utf8') as qf:
            questionnaire_data = list(yaml.round_trip_load_all(qf))
        questions = [q for q in questionnaire_data if q['kind'] not in ('config', 'header')]
        args = arg.lower().split()
        if len(args) == 0:
            args = ['']
        question_ids = [f'q_{1 + i}' for i in range(len(questions))]
        title = None
        if args[0] == 'mods':
            args[0] = 'q_60'
        if args[0] == 'count':
            sql = 'SELECT COUNT(*) FROM "Votes"'
            result_type = 'single'
            _, rows = self._survey_database_query(sql)
        elif args[0] in ('questions', 'questions_full'):
            trunc_length = 60 if args[0] == 'questions' else 200
            result_type = 'table'
            cols = ['Question Number', 'Type', 'Title']
            rows = [(f"\u266f{1 + i}", q['kind'], self._truncate(q['title'], trunc_length)) for i, q in
                    enumerate(questions)]
        elif args[0] == 'votes_per_day':
            sql = SQL_SURVEY_PARTICIPATION
            result_type = 'table'
            cols, rows = self._survey_database_query(sql)
        elif args[0] in question_ids:
            question_id = int(args[0].split('_')[-1])
            result_type = 'table'
            title, cols, rows = self._survey_question(questions, question_id)
        elif args[0] == 'full_replies':
            result_type = 'full_table'
            if len(args) > 1 and args[1] == 'json':
                result_type = 'full_table_json'
            result = []
            for question_text_id in question_ids:
                question_id = int(question_text_id.split('_')[-1])
                title, cols, rows = self._survey_question(questions, question_id)
                result.append({'title': title, 'question_code': question_text_id, 'cols': cols, 'rows': rows})
        else:
            valid_queries = ['count', 'questions', 'questions_full', 'mods', 'votes_per_day', 'full_replies'] + \
                            ['q_1', '...', f'q_{str(len(questions))}']
            valid_queries_as_code = [f"`{q}`" for q in valid_queries]
            self._send_text(f"You need to specify a query from {', '.join(valid_queries_as_code)}", is_error=True)
            return

        if result_type == 'single':
            self._send_text(f"*Result*: `{rows[0][0]}`")
        elif result_type == 'table':
            table = self.make_table(title, cols, rows)
            self._send_file(table, title=title, filetype='markdown')
        elif result_type == 'full_table':
            filedata = b''
            with tempfile.TemporaryFile() as tmpfile:
                workbook = xlsxwriter.Workbook(tmpfile)
                for question_response in result:
                    worksheet = workbook.add_worksheet()
                    worksheet.name = question_response['question_code']
                    title = question_response['title']
                    cols = question_response['cols']
                    rows = question_response['rows']

                    worksheet.write('A1', title)
                    for col_number, col in enumerate(cols):
                        worksheet.write(2, col_number, col)
                    for row_number, row in enumerate(rows):
                        for col_number, col in enumerate(cols):
                            worksheet.write(3 + row_number, col_number, row[col_number])
                    # table = self.make_table(title, cols, rows)
                    # full_table += table + '\n\n'
                workbook.close()
                tmpfile.flush()
                tmpfile.seek(0, io.SEEK_SET)
                filedata = tmpfile.read()
            self._send_file(filedata, filename="Survey_Results.xlsx", title="Survey Results", filetype='xlsx')
        elif result_type == 'full_table_json':
            filedata = json.dumps(result)
            self._send_file(filedata, filename='Survey_Results.json', title="Survey Results", filetype="json")

    def make_table(self, title, cols, rows):
        table = tabulate(rows, headers=cols, tablefmt='pipe')
        if title:
            table = f"## *{title}*\n\n" + table
        return table

    def _survey_question(self, questions, question_id):
        question = questions[question_id - 1]
        title = question['title']
        if question['kind'] in ('checktree', 'checkbox', 'tree', 'radio'):
            cols, rows = self._survey_database_query(SQL_SURVEY_PREFILLED_ANSWERS.format(question_id))
            choices = {}
            if question['kind'] in ('tree', 'checktree'):
                # flatten choices tree
                choices = self._flatten_choices(question['choices'])
            elif question['kind'] in ('radio', 'checkbox'):
                choices = question['choices']
            rows = [self._translate_choice(choices, row) for row in rows]
            cols = ["Vote Value", "Vote Count"]
        elif question['kind'] in ('text', 'textarea'):
            cols, rows = self._survey_database_query(SQL_SURVEY_TEXT.format(question_id))
        elif question['kind'] in ('scale-matrix',):
            cols, rows = self._survey_database_query(SQL_SURVEY_SCALE_MATRIX.format(question_id))
            rows = [self._translate_matrix(question['choices'], question['lines'], row) for row in rows]
        else:
            cols = ['Message']
            rows = [('Not implemented',)]
        return title, cols, rows

    @staticmethod
    def _truncate(text, length):
        if len(text) <= length:
            return text
        else:
            return text[:length - 3] + '...'

    @staticmethod
    def _translate_choice(choices, row):
        choice_value = row[0]
        choice_other = row[1]
        choice_count = row[2]
        if choice_value == 'text':
            choice_value = 'Other:' + choice_other
        elif choice_value is None:
            choice_value = choices.get(choice_other)
        else:
            choice_value = choices.get(choice_value)
        return choice_value, choice_count

    @staticmethod
    def _translate_matrix(choices, lines, row):
        line = int(row[0])
        answer = int(row[1])
        count = row[2]
        answer_key = list(choices.keys())[answer - 1]
        return lines[line - 1] or '<empty>', choices[answer_key], count

    @staticmethod
    def _survey_database_query(sql):
        database_url = os.environ['QUESTIONNAIRE_DATABASE_URL']
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [col.name for col in cur.description]
        cur.close()
        conn.close()
        return cols, rows

    @staticmethod
    def _flatten_choices(choices):
        # parent
        result = dict([(k, choices[k]['title']) for k in list(choices.keys())])
        for choice_name, choice in choices.items():
            if 'choices' not in choice:
                continue
            children = SlackbotShell._flatten_choices(choice['choices'])
            for child_name, child_title in children.items():
                result[child_name] = child_title
        return result

    @staticmethod
    def _archive_page(url):
        ARCHIVE_URL = 'http://archive.is'
        USER_AGENT = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64)  '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/73.0.3683.86 Safari/537.36')
        # PROXY = 'http://45.250.226.14:8080'

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
        Accepted values are 24 (default), 48, 72, A_WEEK, TWO_WEEKS, A_MONTH, FOREVER_AND_EVER
        Add SUBMISSIONS or POSTS to remove submissions as well.
        """
        global r
        global sc
        global subreddit_name
        CUTOFF_AGES = {'24': 1, '48': 2, '72': 3, 'A_WEEK': 7, 'TWO_WEEKS': 14, 'A_MONTH': 30,
                       'FOREVER_AND_EVER': 36525}
        # FOREVER_AND_EVER is 100 years. Should be enough.

        username, *rest_of_text = arg.split()

        rest_of_text = [t.upper() for t in rest_of_text]

        remove_submissions_as_well = False
        for arg_text in ('POSTS', 'SUBMISSIONS'):
            if arg_text in rest_of_text:
                rest_of_text.remove(arg_text)
                remove_submissions_as_well = True
        if rest_of_text:
            timeframe = rest_of_text[0]
        else:
            timeframe = '24'
        if timeframe not in CUTOFF_AGES:
            self._send_text(f'{timeframe} is not an acceptable timeframe', is_error=True)
            return
        if re.match('[a-zA-Z0-9_-]+', username):
            pass
        elif re.match(r'<https://www\.reddit\.com/(u|user)/[a-zA-Z0-9_-]+>', username):
            username = username.split('/')[-1][:-1]
        elif re.match(r'u/[a-zA-Z0-9_-]+', username):
            username = username.split('/')[-1]
        else:
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
                other_subreddit_history[comment_subreddit_name] = \
                    other_subreddit_history.get(comment_subreddit_name, 0) + 1
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
        if remove_submissions_as_well:
            all_submissions = u.posts.new(limit=None)
            already_removed_submissions = 0
            removed_submissions = 0
            other_subreddit_submissions = 0
            too_old_submissions = 0
            for s in all_submissions:
                submission_subreddit_name = s.subreddit.display_name.lower()
                if submission_subreddit_name != subreddit_name:
                    other_subreddits += 1
                    other_subreddit_history[submission_subreddit_name] = \
                        other_subreddit_history.get(submission_subreddit_name, 0) + 1
                    continue
                if s.banned_by and s.banned_by != 'AutoModerator':
                    already_removed += 1
                    continue
                submission_created = datetime.datetime.fromtimestamp(c.created_utc)
                submission_age = now - submission_created
                if submission_age.days > cutoff_age:
                    too_old += 1
                    continue
                c.mod.remove()
                removed_submissions += 1
            result += (
                f"Removed {removed_submissions} submissions.\n"
                f"{other_subreddit_submissions} submissions in other subreddits.\n"
                f"{already_removed_submissions} submissions were already removed.\n"
                f"{too_old_submissions} submissions were too old for the {timeframe} timeframe.\n"
            )
        self._send_text(result)

    def do_binary(self, arg):
        """Convert binary to text"""
        rest_of_text = ' '.join(arg.split())
        decoded_text = ''.join([chr(int(c, 2)) for c in rest_of_text.split()])
        self._send_text(''.join(decoded_text))

    do_bin = do_binary

    def do_kudos(self, arg):
        """Add kudos to user.

        Syntax:
        kudos @username to give kudos to username
        kudos view to see all kudos so far
        kudos view 15 to see kudos given last 15 days
        """
        global users, teams, channels
        args = arg.split()
        if re.match(r'<@\w+>', arg):
            recipient_user_id = arg[2:-1]
            get_user_info(recipient_user_id)
            get_channel_info(self.team_id, self.channel_id)
            recipient_name = users[recipient_user_id]['name']
            sender_name = users[self.user_id]['name']

            if recipient_user_id == self.user_id:
                self._send_text("You can't give kudos to yourself, silly!", is_error=True)
                return

            database_url = os.environ['KUDOS_DATABASE_URL']
            conn = psycopg2.connect(database_url)
            conn.autocommit = True
            cur = conn.cursor()
            cmd_vars = {
                'sender_name': sender_name, 'sender_id': self.user_id,
                'recipient_name': recipient_name, 'recipient_id': recipient_user_id,
                'team_name': teams[self.team_id]['name'], 'team_id': self.team_id,
                'channel_name': channels[self.team_id][self.channel_id], 'channel_id': self.channel_id,
                'permalink': self.permalink['permalink']}
            cur.execute(SQL_KUDOS_INSERT, vars=cmd_vars)
            success = cur.rowcount > 0
            cur.close()
            conn.close()
            if success:
                self._send_text(f"Kudos from {sender_name} to {recipient_name}")
            else:
                self._send_text("Kudos not recorded")
        elif args[0].lower() == 'view':
            if len(args) > 1 and re.match(r'\d{1,3}', args[1]):
                days_to_check = int(args[1])
            else:
                days_to_check = 365 * 100
            database_url = os.environ['KUDOS_DATABASE_URL']
            conn = psycopg2.connect(database_url)
            cur = conn.cursor()
            cur.execute(SQL_KUDOS_VIEW, {'days': days_to_check})
            rows = cur.fetchall()
            cols = [col.name for col in cur.description]
            cur.close()
            conn.close()
            if len(rows) == 0:
                self._send_text("No kudos yet!")
            else:
                table = tabulate(rows, headers=cols, tablefmt='pipe')
                self._send_file(table, title="Kudos", filetype='markdown')
        else:
            self._send_text(("You need to specify a user "
                             "(i.e. @pikos_apikos) or "
                             "'view' to see leaderboard"), is_error=True)

    def do_joke(self, arg):
        """Tell a joke"""
        joke_page = requests.get('https://icanhazdadjoke.com/', headers={
            'Accept': 'text/plain',
            'User-Agent': 'Slack Bot for Reddit (https://github.com/gschizas/slack-bot)'})
        joke_text = joke_page.content
        self._send_text(joke_text.decode())


if __name__ == '__main__':
    main()
