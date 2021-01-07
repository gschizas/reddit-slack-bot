import base64
import cmd
import collections
import ctypes
import datetime
import io
import json
import math
import os
import pathlib
import random
import re
import subprocess
import tempfile
import urllib.parse
import zlib
from contextlib import contextmanager

import praw
import prawcore
import psycopg2
import requests
import xlsxwriter
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from tabulate import tabulate

from bot_framework.yaml_wrapper import yaml
from constants import SQL_SURVEY_PREFILLED_ANSWERS, SQL_SURVEY_TEXT, SQL_SURVEY_SCALE_MATRIX, SQL_SURVEY_PARTICIPATION, \
    SQL_KUDOS_INSERT, SQL_KUDOS_VIEW, ARCHIVE_URL, CHROME_USER_AGENT, MAGIC_8_BALL_OUTCOMES, DICE_REGEX, \
    WIKI_PAGE_BAD_FORMAT

_ntuple_diskusage = collections.namedtuple('usage', 'total used free')


@contextmanager
def state_file(path):
    data = {}
    log_name = os.environ.get('LOG_NAME', 'unknown')
    data_file = pathlib.Path(f'data/{path}-{log_name}.yml')
    if data_file.exists():
        with data_file.open(mode='r', encoding='utf8') as y:
            data = dict(yaml.load(y))
            if not data:
                data = {}
    yield data
    with data_file.open(mode='w', encoding='utf8') as y:
        yaml.dump(data, y)


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
        self.sc = None
        self.users = None
        self.logger = None
        self.reddit_session = None
        self.bot_reddit_session = None
        self.subreddit_name = None
        self.archive_session = None
        self.users = {}
        self.teams = {}
        self.channels = {}
        self.archive_session = requests.Session()
        self.archive_session.mount(ARCHIVE_URL, HTTPAdapter(max_retries=5))

    def _send_text(self, text, is_error=False):
        icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        self.sc.api_call("chat.postMessage",
                         channel=self.channel_id,
                         text=text,
                         icon_emoji=icon_emoji,
                         username=self.trigger_words[0])

    def _send_file(self, file_data, title=None, filename=None, filetype=None):
        self.sc.api_call("files.upload",
                         channels=self.channel_id,
                         icon_emoji=':robot_face:',
                         username=self.trigger_words[0],
                         file=file_data,
                         filename=filename,
                         title=title,
                         filetype=filetype or 'auto')

    def _send_fields(self, text, fields):
        self.sc.api_call("chat.postMessage",
                         channel=self.channel_id,
                         icon_emoji=':robot_face:',
                         text=text,
                         username=self.trigger_words[0],
                         attachments=fields)

    def preload(self, user_id, team_id, channel_id):
        self._slack_team_info(team_id)
        self._slack_user_info(user_id)
        self._slack_channel_info(team_id, channel_id)

    def precmd(self, line):
        i, n = 0, len(line)
        while i < n and line[i] in self.identchars: i += 1
        return line[:i].lower() + line[i:]

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
        instant_answer_page = requests.get("https://api.duckduckgo.com/", params={'q': line, "format": "json"})
        instant_answer = instant_answer_page.json()
        # self._send_file(instant_answer_page.content, filename='duckduckgo.json', filetype='application/json')
        if isinstance(instant_answer["Answer"], str) and instant_answer["Answer"]:
            self._send_text(instant_answer["Answer"])
            if 'Image' in instant_answer:
                self._send_text(instant_answer['Image'])
        elif instant_answer["AbstractText"]:
            self._send_text(instant_answer["AbstractText"])
            if 'Image' in instant_answer:
                self._send_text(instant_answer['Image'])
        elif instant_answer['RelatedTopics']:
            topic = instant_answer['RelatedTopics'][0]
            self._send_text(topic['Text'])
            if 'Icon' in topic:
                self._send_text(topic['Icon']['URL'])
        else:
            self._send_text(
                f"```I don't know what to do with {line}.\nTry one of the following commands:\n```",
                is_error=True)
            self.do_help('')

    def emptyline(self):
        self._send_text("```You need to provide a command. Try these:```\n", is_error=True)
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
        """Display the weather in any place.

        Syntax: weather PLACE

        if PLACE is skipped, the location from the last query is used.
        """
        place = arg.lower()

        with state_file('weather') as pref_cache:
            if place:
                pref_cache[self.user_id] = place
            else:
                place = pref_cache.get(self.user_id, '')

        if place == 'macedonia' or place == 'makedonia':
            place = 'Thessaloniki'
        if place == '':
            self._send_text(
                ('You need to first set a default location\n'
                 f'Try `{self.trigger_words[0]} weather LOCATION`'), is_error=True)
            return
        place = place.replace("?", "")
        if place in ('brexit', 'pompeii'):
            title = 'the floor is lava'
            with open('img/lava.png', 'rb') as f:
                file_data = f.read()
        else:
            weather = requests.get('http://wttr.in/' + place + '_p0.png?m')
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
        self.logger.info(prices_page.url)
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
        if (redditor_username := self._extract_username(redditor_username)) is None:
            self._send_text(f'{redditor_username} is not a valid username', is_error=True)
            return
        verbose = args[1] if len(args) == 2 else ''
        if verbose.lower() not in ('short', 'long'):
            verbose = ''
        tb_notes = self.sr.wiki['usernotes']
        tb_notes_1 = json.loads(tb_notes.content_md)
        warnings = tb_notes_1['constants']['warnings']
        tb_notes_2 = CaseInsensitiveDict(json.loads(zlib.decompress(base64.b64decode(tb_notes_1['blob'])).decode()))
        tb_config = json.loads(self.sr.wiki['toolbox'].content_md)
        usernote_colors = {c['key']: c for c in tb_config['usernoteColors']}
        notes = tb_notes_2.get(redditor_username.lower())
        if notes is None:
            self._send_text(f"user {redditor_username} doesn't have any user notes")
            return

        mod_names = tb_notes_1['constants']['users']

        self._send_usernote(redditor_username, notes, warnings, usernote_colors, mod_names, verbose)
        return

    def _send_usernote(self, redditor_username, notes, warnings, usernote_colors, mod_names, verbose):
        text = f'Usernotes for user {redditor_username}'
        fields = []
        for note in notes['ns']:
            warning = warnings[note['w']] or ''
            when = datetime.datetime.fromtimestamp(note['t'])
            note_text = note['n']
            color = usernote_colors.get(warning, {'color': '#000000'})['color']
            warning_text = usernote_colors.get(warning, {'text': '?' + warning})['text']
            # breakpoint()
            link_parts = note['l'].split(',')
            link_href = '???'
            if link_parts[0] == 'l':
                if len(link_parts) == 2:
                    link_href = f'{self.reddit_session.config.reddit_url}/r/{self.sr.display_name}/comments/{link_parts[1]}'
                elif len(link_parts) == 3:
                    link_href = (
                        f'{self.reddit_session.config.reddit_url}/r/{self.sr.display_name}/comments/'
                        f'{link_parts[1]}/-/{link_parts[2]}')
            else:
                link_href = note['l']
            mod_name = mod_names[note['m']]
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
            text += self.reddit_session.config.reddit_url + c.permalink + '\n```\n' + c.body[:80] + '\n```\n'
        self._send_text(text)

    def do_youtube_info(self, arg):
        """Get YouTube media URL"""
        self.logger.debug(arg)
        post = self.reddit_session.submission(url=arg[1:-1])
        post._fetch()
        media = getattr(post, 'media', None)
        if not media:
            self._send_text('Not a YouTube post', is_error=True)
            return
        try:
            author_url = media['oembed']['author_url']
            self._send_text(author_url)
        except Exception as e:
            self._send_text(repr(e), is_error=True)

    def do_fortune(self, args):
        """Like a Chinese fortune cookie, but less yummy"""
        self._send_text(subprocess.check_output(['/usr/games/fortune']).decode())

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
        thread_id = self._extract_real_thread_id(thread_id)
        post = self.reddit_session.submission(thread_id)
        post.comments.replace_more(limit=None)
        comments = post.comments.list()
        post.mod.remove()
        comments_removed = []
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
            comments_removed.append(comment.id)
        post.mod.lock()
        result = (
            f"{len(comments_removed)} comments were removed.\n"
            f"{comments_distinguished} distinguished comments were kept.\n"
            f"{comments_already_removed} comments were already removed.\n"
            "Submission was locked")
        with state_file('nuke_thread') as state:
            state[thread_id] = comments_removed
        self._send_text(result)

    @staticmethod
    def _extract_real_thread_id(thread_id):
        if '/' in thread_id:
            if thread_id.startswith('<') and thread_id.endswith('>'):  # slack link
                thread_id = thread_id[1:-1]
            if thread_id.startswith('http://') or thread_id.startswith('https://'):
                thread_id = thread_id.split('/')[6]
            elif thread_id.startswith('/'):
                thread_id = thread_id.split('/')[4]
            else:
                thread_id = thread_id.split('/')[3]
        return thread_id

    def do_undo_nuke_thread(self, thread_id):
        """Undo previous nuke thread
        Thread ID should be either the submission URL or the submission id"""
        thread_id = self._extract_real_thread_id(thread_id)
        with state_file('nuke_thread') as state:
            if thread_id not in state:
                self._send_text(f"Could not find thread {thread_id}", is_error=True)
                return
            removed_comments = state.pop(thread_id)
            for comment_id in removed_comments:
                comment = self.reddit_session.comment(comment_id)
                comment.mod.approve()
            self._send_text(f"Nuking {len(removed_comments)} comments was undone")

    def do_add_policy(self, title):
        """Add a minor policy change done via Slack's #modpolicy channel"""
        permalink_response = self.sc.api_call(
            'chat.getPermalink',
            channel=self.channel_id,
            message_ts=self.message['ts'])
        permalink = permalink_response['permalink']
        policy_subreddit = os.environ.get('REDDIT_POLICY_SUBREDDIT', self.subreddit_name)
        policy_page = os.environ.get('REDDIT_POLICY_PAGE', 'mod_policy_votes')
        sr = self.reddit_session.subreddit(policy_subreddit)
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
        bonus = 0
        args = arg.split()
        if len(args) >= 1 and args[0].lower() == 'statline':
            min_roll = 1
            if len(args) > 1 and args[1] == 'drop1':
                min_roll = 2
            ability_text = ""
            for roll_line in range(6):
                ability_line = []
                for roll_dice in range(4):
                    dice = random.randint(min_roll, 6)
                    ability_line.append(dice)
                ability_line_sorted = sorted(ability_line)[1:]
                ability_text += (
                    f"You rolled 4d6: {', '.join([str(a) for a in ability_line])}."
                    f" Keeping {', '.join([str(a) for a in ability_line_sorted])},"
                    f" for a sum of *{sum(ability_line_sorted)}*.\n")
            self._send_text(ability_text)
            return
        elif len(args) >= 1 and args[0].lower() == 'magic8':
            result = random.choice(MAGIC_8_BALL_OUTCOMES)
            self._send_text(result)
            return
        elif len(args) > 0:
            dice_spec = re.match(DICE_REGEX, arg.strip())
            if dice_spec:
                if dice_spec.group('Times'):
                    times = int(dice_spec.group('Times'))
                if dice_spec.group('Bonus'):
                    bonus = int(dice_spec.group('Bonus'))
                if dice_spec.group('Sides'):
                    sides = int(dice_spec.group('Sides'))
        if sides < 2: sides = 6
        if times < 1: times = 1
        rolls = []
        for roll_index in range(times):
            rolls.append(random.randint(1, sides))
        final_roll = sum(rolls) + bonus
        roll_text = ', '.join(map(str, rolls))
        times_text = 'time' if times == 1 else 'times'
        self._send_text((
            f"You rolled a {sides}-sided dice {times} {times_text} with a bonus of +{bonus}."
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
            questionnaire_data = list(yaml.load_all(qf))
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
    def _archive_page(self, url):
        url = url.replace('//www.reddit.com/', '//old.reddit.com/')

        # start_page = requests.get(ARCHIVE_URL)
        # soup = BeautifulSoup(start_page.text, 'lxml')
        # main_form = soup.find('form', {'id': 'submiturl'})
        # submit_id = main_form.find('input', {'name': 'submitid'})['value']
        p2 = self.archive_session.post(
            f'{ARCHIVE_URL}/submit/',
            data={
                'url': url
            },
            headers={
                'Referer': 'http://archive.is',
                'User-Agent': CHROME_USER_AGENT})
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
        if (username := self._extract_username(username)) is None:
            self._send_text(f'{username} is not a valid username', is_error=True)
            return
        user = self.reddit_session.redditor(username)

        urls_to_archive = []
        urls_to_archive.append(f'{self.reddit_session.config.reddit_url}/user/{user.name}/submitted/')

        submissions = list(user.submissions.new(limit=None))
        for s in submissions:
            urls_to_archive.append(self.reddit_session.config.reddit_url + s.permalink)

        comments = list(user.comments.new(limit=None))
        url_base = f'{self.reddit_session.config.reddit_url}/user/{user.name}/comments?sort=new'
        urls_to_archive.append(url_base)
        for c in comments[24::25]:
            after = c.name
            url = url_base + '&count=25&after=' + after
            urls_to_archive.append(url)
        self._send_file(
            file_data='\n'.join(urls_to_archive).encode(),
            filename=f'archive-{user}-request.txt',
            filetype='text/plain')
        final_urls = [self._archive_page(url) for url in urls_to_archive]
        self._send_file(
            file_data='\n'.join(final_urls).encode(),
            filename=f'archive-{user}-response.txt',
            filetype='text/plain')

    def do_nuke_user(self, arg):
        """\
        Nuke the comments of a user. Append the timeframe to search.
        Accepted values are 24 (default), 48, 72, A_WEEK, TWO_WEEKS, A_MONTH, THREE_MONTHS, FOREVER_AND_EVER
        Add SUBMISSIONS or POSTS to remove submissions as well.
        """
        global sc
        CUTOFF_AGES = {'24': 1, '48': 2, '72': 3, 'A_WEEK': 7, 'TWO_WEEKS': 14, 'A_MONTH': 30, 'THREE_MONTHS': 90,
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
        if (username := self._extract_username(username)) is None:
            self._send_text(f'{username} is not a valid username', is_error=True)
            return
        u = self.reddit_session.redditor(username)
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
            if comment_subreddit_name != self.subreddit_name:
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
            all_submissions = u.submissions.new(limit=None)
            already_removed_submissions = 0
            removed_submissions = 0
            other_subreddit_submissions = 0
            too_old_submissions = 0
            for s in all_submissions:
                submission_subreddit_name = s.subreddit.display_name.lower()
                if submission_subreddit_name != self.subreddit_name:
                    other_subreddits += 1
                    other_subreddit_history[submission_subreddit_name] = \
                        other_subreddit_history.get(submission_subreddit_name, 0) + 1
                    continue
                if s.banned_by and s.banned_by != 'AutoModerator':
                    already_removed_submissions += 1
                    continue
                submission_created = datetime.datetime.fromtimestamp(s.created_utc)
                submission_age = now - submission_created
                if submission_age.days > cutoff_age:
                    too_old += 1
                    continue
                s.mod.remove()
                removed_submissions += 1
            result += (
                f"Removed {removed_submissions} submissions.\n"
                f"{other_subreddit_submissions} submissions in other subreddits.\n"
                f"{already_removed_submissions} submissions were already removed.\n"
                f"{too_old_submissions} submissions were too old for the {timeframe} timeframe.\n"
            )
        self._send_text(result)

    @staticmethod
    def _extract_username(username):
        if re.match('[a-zA-Z0-9_-]+', username):
            pass
        elif m := re.match(r'<https://www.reddit.com/user/(?P<username>[a-zA-Z0-9_-]+)(?:\|\1)?>', username):
            username = m.group('username')
        elif re.match(r'u/[a-zA-Z0-9_-]+', username):
            username = username.split('/')[-1]
        else:
            username = None
        return username

    def do_binary(self, arg):
        """Convert binary to text"""
        rest_of_text = ' '.join(arg.split())
        rest_of_text = re.sub(r'(\S{8})\s?', r'\1 ', rest_of_text)
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
        args = arg.split()
        if len(args) == 0:
            self._send_text(("You need to specify a user "
                             "(i.e. @pikos_apikos) or "
                             "'view' to see leaderboard"), is_error=True)
            return
        if re.match(r'<@\w+>', args[0]):
            recipient_user_id = args[0][2:-1]
            self._slack_user_info(recipient_user_id)
            self._slack_channel_info(self.team_id, self.channel_id)
            recipient_name = self.users[recipient_user_id]['name']
            sender_name = self.users[self.user_id]['name']
            reason = ' '.join(args[1:])

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
                'team_name': self.teams[self.team_id]['name'], 'team_id': self.team_id,
                'channel_name': self.channels[self.team_id][self.channel_id], 'channel_id': self.channel_id,
                'permalink': self.permalink['permalink'], 'reason': reason}
            cur.execute(SQL_KUDOS_INSERT, vars=cmd_vars)
            success = cur.rowcount > 0
            cur.close()
            conn.close()
            if success:
                text_to_send = f"Kudos from {sender_name} to {recipient_name}"
                give_gift = random.random()
                if reason.strip():
                    if re.search(':\w+:', reason):
                        reason = '. No cheating! Only I can send gifts!'
                        give_gift = -1
                    text_to_send += ' ' + reason
                GIFTS = 'balloon bear lollipop cake pancakes apple pineapple cherries grapes pizza popcorn rose tulip baby_chick beer doughnut cookie'.split()
                if give_gift > 0.25:
                    if not text_to_send.endswith('.'): text_to_send += '.'
                    gift = random.choice(GIFTS)
                    text_to_send += f" Have a :{gift}:"
                self._send_text(text_to_send)
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

    def do_history(self, arg):
        """\
        Return full user comment history, including deleted comments
        This should work for deleted users as well
        Data comes from pushshift.io"""
        username, *rest_of_text = arg.split()
        comments = requests.get(
            "http://api.pushshift.io/reddit/comment/search",
            params={
                'limit': 40,
                'author': username,
                'subreddit': self.subreddit_name}).json()
        if not comments['data']:
            self._send_text(f"User u/{username} has no comments in r/{self.subreddit_name}")
            return
        comment_full_body = [comment['body'] for comment in comments['data']]
        self._send_file(
            file_data='\n'.join(comment_full_body).encode(),
            filename=f'comment_history-{username}.txt',
            filetype='text/plain')

    def do_disk_space(self, arg):
        """\
        Display free disk space"""
        self._send_text(self._diskfree())

    @staticmethod
    def _mock_config():
        if os.environ['MOCK_CONFIGURATION'].startswith('/'):
            config_file = pathlib.Path(os.environ['MOCK_CONFIGURATION'])
        else:
            config_file = pathlib.Path('config') / os.environ['MOCK_CONFIGURATION']
        with config_file.open() as f:
            mock_config = json.load(f)
        return mock_config

    def do_mock(self, arg):
        """Switch openshift mock status on environment"""
        args = arg.split()
        if len(args) != 2:
            self._send_text(f"Syntax is {self.trigger_words[0]} mock «ENVIRONMENT» «STATUS»", is_error=True)
            return
        mock_config = self._mock_config()
        if self.user_id not in mock_config['allowed_users']:
            self._send_text(f"You don't have permission to switch mock status.", is_error=True)
            return
        environment = args[0].upper()
        mock_status = args[1].upper()
        env_vars = mock_config['env_vars']
        valid_environments = [e.upper() for e in mock_config['environments']]
        if environment not in valid_environments:
            self._send_text((f"Invalid project `{environment}`. "
                             f"Environment must be one of {', '.join(valid_environments)}"), is_error=True)
            return
        valid_mock_statuses = [k.upper() for k in mock_config['environments'][environment]['status'].keys()]
        if mock_status not in valid_mock_statuses:
            self._send_text((f"Invalid status `{mock_status}`. "
                             f"Mock status must be one of {', '.join(valid_mock_statuses)}"), is_error=True)
            return

        oc_token = mock_config['environments'][environment]['openshift_token']
        site = mock_config['site']
        login_command = ['oc', 'login', site, f'--token={oc_token}']
        result_text = subprocess.check_output(login_command).decode() + '\n' * 3
        prefix = mock_config['prefix']
        self._send_text(f"Setting mock status to {mock_status} for project {environment}...")
        change_project_command = ['oc', 'project', environment.lower()]
        result_text += subprocess.check_output(change_project_command).decode() + '\n' * 3
        statuses = mock_config['environments'][environment]['status'][mock_status]
        for microservice_info, status in statuses.items():
            if '$' not in microservice_info: microservice_info += '$'
            microservice, env_var_shortcut = microservice_info.split('$')
            env_var_name: str = env_vars[env_var_shortcut]
            env_variable_value = f'{env_var_name}={status}' if status is not None else f'{env_var_name}-'
            environment_set_command = ['oc', 'set', 'env', prefix + microservice, env_variable_value]
            result_text += subprocess.check_output(environment_set_command).decode() + '\n\n'
        logout_command = ['oc', 'logout']
        result_text += subprocess.check_output(logout_command).decode() + '\n\n'
        result_text = re.sub('\n{2,}', '\n', result_text)
        self._send_text('```' + result_text + '```')

    def do_check_mock(self, arg):
        """View current status of environment"""
        args = arg.split()
        mock_config = self._mock_config()
        if self.user_id not in mock_config['allowed_users']:
            self._send_text(f"You don't have permission to view mock status.", is_error=True)
        oc_token = mock_config['openshift_token']
        site = mock_config['site']
        result_text = subprocess.check_output(['oc', 'login', site, f'--token={oc_token}']).decode() + '\n' * 3
        project = mock_config['project']
        prefix = mock_config['prefix']
        result_text += subprocess.check_output(['oc', 'project', project]).decode() + '\n' * 3
        mock_status = list(mock_config['microservices'].keys())[0]
        for microservice, status in mock_config['microservices'][mock_status].items():
            result_text += subprocess.check_output(['oc', 'env', prefix + microservice, '--list']).decode() + '\n\n'
        result_text += subprocess.check_output(['oc', 'logout']).decode() + '\n\n'
        self._send_file(result_text, title='OpenShift Data', filename='openshift-data.txt')

    def _slack_user_info(self, user_id):
        if user_id not in self.users:
            response_user = self.sc.api_call('users.info', user=user_id)
            if response_user['ok']:
                self.users[user_id] = response_user['user']

    def _slack_team_info(self, team_id):
        if team_id not in self.teams:
            response_team = self.sc.api_call('team.info')
            if response_team['ok']:
                self.teams[team_id] = response_team['team']

    def _slack_channel_info(self, team_id, channel_id):
        if team_id not in self.channels:
            self.channels[team_id] = {}
        if channel_id not in self.channels[team_id]:
            response_channel = self.sc.api_call('conversations.info', channel=channel_id)
            channel_info = response_channel['channel'] if response_channel['ok'] else {}
            if channel_info.get('is_group') or channel_info.get('is_channel'):
                priv = '🔒' if channel_info.get('is_private') else '#'
                self.channels[team_id][channel_id] = priv + channel_info['name_normalized']
            elif channel_info.get('is_im'):
                response_members = self.sc.api_call('conversations.members', channel=channel_id)
                for user_id in response_members['members']:
                    self._slack_user_info(user_id)
                participants = [f"{self.users[user_id]['real_name']} <{self.users[user_id]['name']}@{user_id}>"
                                for user_id in response_members['members']]
                self.channels[team_id][channel_id] = '🧑' + ' '.join(participants)

    @staticmethod
    def _diskfree():
        du = SlackbotShell._disk_usage_raw('/')
        du_text = SlackbotShell._disk_usage_human()
        return SlackbotShell._progress_bar(du.used / du.total, 48) + '\n```\n' + du_text + '\n```\n'

    if hasattr(os, 'statvfs'):  # POSIX
        @staticmethod
        def _disk_usage_raw(path):
            st = os.statvfs(path)
            free = st.f_bavail * st.f_frsize
            total = st.f_blocks * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            return _ntuple_diskusage(total, used, free)

        @staticmethod
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
        @staticmethod
        def _disk_usage_raw(path):
            _, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), \
                             ctypes.c_ulonglong()
            fun = ctypes.windll.kernel32.GetDiskFreeSpaceExW
            ret = fun(path, ctypes.byref(_), ctypes.byref(total), ctypes.byref(free))
            if ret == 0:
                raise ctypes.WinError()
            used = total.value - free.value
            return _ntuple_diskusage(total.value, used, free.value)

        @staticmethod
        def _disk_usage_human():
            disk_usage_command = ['wmic', 'LogicalDisk', 'Where DriveType="3"', 'Get', 'DeviceID,FreeSpace,Size']
            return subprocess.check_output(disk_usage_command).decode()

    @staticmethod
    def _progress_bar(percentage, size):
        filled = math.ceil(size * percentage)
        empty = math.floor(size * (1 - percentage))
        bar = '\u2588' * filled + '\u2591' * empty
        return bar

    def do_comment_source(self, arg):
        """Get comment source
        Syntax:
        comment_source comment_thing_id
        comment_source comment_full_url"""
        self.logger.debug(arg)
        if '/' in arg:
            comment_id = praw.models.Comment.id_from_url(arg)
        else:
            comment_id = arg

        try:
            comment = self.reddit_session.comment(comment_id)
            comment._fetch()
            self._send_file(comment.body.encode('unicode_escape'), filename=f'comment_{comment_id}.md')
        except Exception as e:
            self._send_text(repr(e), is_error=True)
        pass

    def do_deleted_comment_source(self, arg):
        """\
        Return comment source even if deleted. Use comment ids
        Data comes from pushshift.io"""
        ids = ','.join(arg.split())
        comments = requests.get(
            "http://api.pushshift.io/reddit/comment/search",
            params={
                'limit': 40,
                'ids': ids,
                'subreddit': self.subreddit_name}).json()
        if not comments['data']:
            self._send_text(f"No comments under those ids were found in r/{self.subreddit_name}")
            return
        comment_full_body = [comment['body'] for comment in comments['data']]
        self._send_file(
            file_data='\n'.join(comment_full_body).encode(),
            filename=f'comment_body-{ids}.txt',
            filetype='text/plain')

    def do_make_post(self, arg):
        """
        Create or update a post as the common moderator user. It reads the provided wiki page and creates or updates
        a post according to the included data.

        Note that there's no need for a separate wiki page for each post, the wiki page can be reused
        
        Syntax:
        make_post NEW wiki_page
        make_post thread_id wiki_page
        make_post thread_id wiki_page version_id"""
        args = arg.split()
        if len(args) == 2:
            thread_id, wiki_page_name = args
            revision_id = 'LATEST'
        elif len(args) == 3:
            thread_id, wiki_page_name, revision_id = args
        else:
            self._send_text(self.do_make_post.__doc__, is_error=True)
            return

        sr = self.bot_reddit_session.subreddit(self.subreddit_name)
        wiki_lines = self._get_wiki_text(sr, wiki_page_name, revision_id)
        if len(wiki_lines) < 2:
            self._send_text(WIKI_PAGE_BAD_FORMAT, is_error=True)
            return
        if wiki_lines[0].startswith("# ") and wiki_lines[1] == '':
            wiki_title = wiki_lines[0][2:]
            wiki_text_body = '\n'.join(wiki_lines[2:])
        else:
            self._send_text(WIKI_PAGE_BAD_FORMAT, is_error=True)
            return

        if thread_id.upper() == 'NEW':
            submission = sr.submit(wiki_title, wiki_text_body)
            self._send_text(self.bot_reddit_session.config.reddit_url + submission.permalink)
        else:
            submission = self.bot_reddit_session.submission(thread_id)
            submission.edit(wiki_text_body)
            self._send_text(self.bot_reddit_session.config.reddit_url + submission.permalink)

    @staticmethod
    def _get_wiki_text(sr, wiki_page_name, revision_id=None):
        if revision_id is None: revision_id = 'LATEST'
        wiki_page = sr.wiki[wiki_page_name]
        # If wiki page is not protected (i.e. "Only mods may edit and view"), protect it.
        if wiki_page.mod.settings()['permlevel'] != 2:
            wiki_page.mod.update(permlevel=2, listed=True)
        wiki_text = wiki_page.content_md if revision_id == 'LATEST' else wiki_page.revision[revision_id].content_md
        wiki_lines = wiki_text.splitlines()
        return wiki_lines

    def do_make_sticky(self, arg):
        """
        Create or update a sticky comment as the common moderator user. It reads the provided wiki page and creates or
        updates the comment according to the included data.

        Note that there's no need for a separate wiki page for each post, the wiki page can be reused

        Syntax:
        make_sticky thread_id wiki_page
        make_sticky thread_id wiki_page version_id"""
        args = arg.split()
        if len(args) == 2:
            thread_id, wiki_page_name = args
            revision_id = 'LATEST'
        elif len(args) == 3:
            thread_id, wiki_page_name, revision_id = args
        else:
            self._send_text(self.do_make_sticky.__doc__, is_error=True)
            return

        sr = self.bot_reddit_session.subreddit(self.subreddit_name)
        wiki_lines = self._get_wiki_text(sr, wiki_page_name, revision_id)
        wiki_text_body = '\n'.join(wiki_lines)

        submission = self.bot_reddit_session.submission(thread_id)
        sticky_comments = [c for c in submission.comments.list()
                           if getattr(c, 'stickied', False) and
                           c.author.name == self.bot_reddit_session.user.me().name]
        if sticky_comments:
            sticky_comment = sticky_comments[0]
            sticky_comment.edit(wiki_text_body)
        else:
            sticky_comment = submission.reply(wiki_text_body)
            sticky_comment.mod.distinguish(how='yes', sticky=True)

        self._send_text(self.bot_reddit_session.config.reddit_url + sticky_comment.permalink)

    def do_covid19(self, arg):
        """Display last available statistics for COVID-19 cases

        Syntax:

        covid19 GR
        covid19 Greece"""
        search_country = arg.lower()
        if search_country == 'usa': search_country = 'us'
        country = None
        with state_file('covid19_countries') as state:
            if not state or 'countries' not in state:
                state['countries'] = requests.get("https://api.covid19api.com/countries").json()
            found_countries = [c for c in state['countries']
                               if search_country == c['Country'].lower()
                               or search_country == c['ISO2'].lower()]
            country = found_countries[0]['Slug'] if len(found_countries) > 0 else None
        if not country:
            self._send_text(f"Country \"{arg}\" not found")
            return

        today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        start_day = today - datetime.timedelta(5)

        result = requests.get(
            f"https://api.covid19api.com/total/country/{country}", params={
                "from": start_day.isoformat(),
                "to": today.isoformat()}, verify=False).json()

        diff_deaths = result[-1]['Deaths'] - result[-2]['Deaths']
        diff_confirmed = result[-1]['Confirmed'] - result[-2]['Confirmed']
        report_date = datetime.datetime.fromisoformat(result[-1]['Date'].replace('Z', '+00:00'))

        self._send_text(f"*Date*:{report_date:%h %d %Y}\n*New* Cases: {diff_confirmed}\n*Deaths*: {diff_deaths}")

    do_covid = do_covid19

    def do_allow_only_regulars(self, arg):
        """Configure the enhanched crowd control

        Syntax:
        list/show: list all current threads
        add THREAD_ID or URL: add a new thread to the monitored threads
        del/remove THREAD_ID or URL: delete the thread from the monitored threads
        """

        subcommand: str = arg.split()[0].lower()
        config_file = pathlib.Path(f'config/enhanced_crowd_control.yml')
        if config_file.exists():
            with config_file.open(mode='r', encoding='utf8') as y:
                config = dict(yaml.load(y))
        if not config:
            config = {self.subreddit_name: {
                'slack': {'channel': '#something', 'url': 'https://hooks.slack.com/services/TEAM_ID/CHANNEL_ID/KEY'}},
                'threads': [{'action': 'remove', 'id': 'xxxxxx', 'last': None}]}
        monitored_threads: list = config[self.subreddit_name]['threads']
        if subcommand in ('list', 'show'):
            text = ""
            for thread_index, thread in enumerate(monitored_threads):
                if 'date' in thread and 'permalink' in thread:
                    submission_date = thread['date']
                    permalink = thread['permalink']
                else:
                    s = self.reddit_session.submission(thread['id'])
                    s.comment_limit = 0
                    s._fetch()
                    submission_date = datetime.datetime.utcfromtimestamp(s.created_utc)
                    permalink = s.permalink
                    thread['date'] = submission_date
                    thread['permalink'] = permalink
                from_date = thread.get('from_date')
                to_date = thread.get('to_date')
                from_date_text = from_date.isoformat() if from_date else "-\u221e"
                to_date_text = to_date.isoformat() if to_date else "+\u221e"
                text += (f"{1 + thread_index}. {self.reddit_session.config.reddit_url}{permalink}\t"
                         f"(on {submission_date:%Y-%m-%d %H:%M:%S UTC}) "
                         f"(monitoring {from_date_text} \u2014 {to_date_text}")
                text += "\n"
            self._send_text(text)
        elif subcommand == 'add':
            thread_id = self._extract_real_thread_id(arg.split(maxsplit=1)[1])
            found = [t for t in monitored_threads if t['id'] == thread_id]
            if found:
                self._send_text(f"Ignoring addition request, {thread_id} has already been added", is_error=True)
            else:
                s = self.reddit_session.submission(thread_id)
                s.comment_limit = 0
                s._fetch()
                submission_date = datetime.datetime.utcfromtimestamp(s.created_utc)
                permalink = s.permalink
                monitored_threads.append({
                    'action': 'remove',
                    'id': thread_id,
                    'last': None,
                    'date': submission_date,
                    'permalink': permalink})
                self._send_text(f"Added {thread_id}")
        elif subcommand in ('del', 'remove'):
            thread_id = self._extract_real_thread_id(arg.split(maxsplit=1)[1])
            remove_me = None
            if '/' not in thread_id and len(thread_id) < 2:
                remove_me = int(thread_id) - 1
                thread_id = monitored_threads[remove_me]['id']
            else:
                for thread_index, thread in enumerate(monitored_threads):
                    if thread['id'] == thread_id:
                        remove_me = thread_index
                        break
            if remove_me is not None:
                monitored_threads.pop(remove_me)
                self._send_text(f"Removed {thread_id}")
            else:
                self._send_text(f"{thread_id} not found", is_error=True)
        else:
            self._send_text(f"I can only understand add, del/remove and list/show")

        with config_file.open(mode='w', encoding='utf8') as y:
            yaml.dump(config, y)

    do_order66 = do_allow_only_regulars
    do_order_66 = do_allow_only_regulars
    do_configure_enhanched_crowd_control = do_allow_only_regulars

    def do_urban_dictionary(self, arg):
        """Search in urban dictionary for the first definition of the word or phrase"""
        definition_page = requests.get('http://api.urbandictionary.com/v0/define', params={'term': arg})
        definition_answer = definition_page.json()
        if len(definition_answer) > 0:
            self._send_text(definition_answer['list'][0]['definition'])
        else:
            self._send_text(f"Could not find anything for {arg}", is_error=True)

    do_ud = do_urban_dictionary
