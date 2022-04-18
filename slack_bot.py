#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import io
import locale
import logging
import os
import string
import sys
import traceback
from typing import TextIO

import praw
import requests
import slack

import commands
import commands.generic
from bot_framework.common import normalize_text
from bot_framework.common import setup_logging
from bot_framework.praw_wrapper import praw_wrapper
from bot_framework.yaml_wrapper import yaml
from chat.slack import SlackWrapper

locale.setlocale(locale.LC_ALL, os.environ.get('LOCALE', ''))

if 'MOCK_CONFIGURATION' in os.environ:
    import commands.openshift.mock

if 'DOCKER_DEPLOY_CONFIGURATION' in os.environ:
    import commands.openshift.docker_deploy

if 'OPENSHIFT_ACTUATOR_REFRESH' in os.environ:
    import commands.openshift.refresh_actuator

if 'CHEESE_DATABASE_URL' in os.environ:
    import commands.cheese

if 'SUBREDDIT_NAME' in os.environ:
    import commands.reddit
    import commands.reddit.nuke

if 'REDDIT_ALT_USER' in os.environ:
    import commands.reddit.bot

if 'QUESTIONNAIRE_DATABASE_URL' in os.environ and 'QUESTIONNAIRE_FILE' in os.environ:
    import commands.reddit.survey

if 'KUDOS_DATABASE_URL' in os.environ:
    import commands.kudos

slack_client: slack.RTMClient = None
logger: logging.Logger = None
real_stdout: TextIO = None
real_stderr: TextIO = None
stdout: TextIO = None
chat_obj: SlackWrapper = None
reddit_session: praw.Reddit = None
bot_reddit_session: praw.reddit.Reddit = None
subreddit: praw.reddit.Subreddit = None
subreddit_name: str = None
trigger_words = []


def init():
    global chat_obj, logger, slack_client, subreddit_name, shortcut_words, bot_name, trigger_words
    global real_stdout, real_stderr, stdout
    global reddit_session, bot_reddit_session, subreddit
    stdout = io.StringIO()
    real_stdout = sys.stdout
    real_stderr = sys.stderr
    sys.stdout = sys.stderr = stdout

    trigger_words = os.environ['BOT_NAME'].split()
    bot_name = trigger_words[0]
    logger.debug(f"Listening for {','.join(trigger_words)}")
    if 'SHORTCUT_WORDS' in os.environ:
        with open('data/' + os.environ['SHORTCUT_WORDS']) as sf:
            shortcut_words = dict(yaml.load(sf))
    else:
        shortcut_words = {}

    chat_obj = SlackWrapper(trigger_words[0])

    slack_api_token = os.environ['SLACK_API_TOKEN']
    subreddit_name = os.environ.get('SUBREDDIT_NAME')
    slack_client = slack.RTMClient(
        token=slack_api_token,
        proxy=os.environ.get('HTTPS_PROXY'))
    if subreddit_name:
        base_user_agent = 'python:gr.terrasoft.reddit.slackmodbot'
        user_agent = f'{base_user_agent}-{subreddit_name}:v0.4 (by /u/gschizas)'
        reddit_session = praw_wrapper(user_agent=user_agent, scopes=['*'])
        subreddit = reddit_session.subreddit(subreddit_name)
        if 'REDDIT_ALT_USER' in os.environ:
            alt_user = os.environ['REDDIT_ALT_USER']
            alt_user_agent = f'{base_user_agent}-{subreddit_name}-as-{alt_user}:v0.4 (by /u/gschizas)'
            bot_reddit_session = praw_wrapper(user_agent=alt_user_agent,
                                              prompt=f'Visit the following URL as {alt_user}:',
                                              scopes=['*'])


def excepthook(type_, value, tb):
    global logger, chat_obj
    # noinspection PyBroadException
    try:
        logger.fatal(type_, value, tb, exc_info=True)
        if chat_obj:
            # noinspection PyBroadException
            try:
                error_text = f"```\n:::Error:::\n{value!r}```\n"
            except Exception:
                error_text = "???"
            chat_obj.send_text(error_text, is_error=True)
    except Exception:
        sys.__excepthook__(type_, value, tb)


@slack.RTMClient.run_on(event='message')
def handle_message(**payload):
    global trigger_words, chat_obj
    msg = payload['data']
    web_client = payload['web_client']
    rtm_client = payload['rtm_client']

    if msg.get('subtype') in ('message_deleted', 'message_replied', 'file_share', 'bot_message', 'slackbot_response'):
        logger.debug(f"Found message of subtype {msg.get('subtype')}")
        return
    if 'message' in msg:
        msg.update(msg['message'])
        del msg['message']

    channel_id = msg['channel']
    team_id = msg.get('team', '')
    user_id = msg.get('user', '')

    permalink = web_client.chat_getPermalink(channel=channel_id, message_ts=msg['ts'])

    chat_obj.load(web_client, team_id, channel_id, user_id, msg, permalink)

    chat_obj.preload(user_id, team_id, channel_id)

    text = msg['text']

    typed_text = normalize_text(text).strip().lower().split()
    if not typed_text:
        return
    first_word = typed_text[0]
    if first_word in shortcut_words:
        replaced_words = shortcut_words[first_word]
        typed_text = replaced_words + typed_text[1:]
        first_word = typed_text[0]
        text = ' '.join(replaced_words) + ' ' + ' '.join(text.split()[1:])
    if not any([first_word == trigger_word for trigger_word in trigger_words]):
        return

    logger.debug(f"Triggerred by {text}")
    line = ' '.join(text.split()[1:])
    try:
        line = precmd(line)
        args = line.split()
        if args[0].lower() == 'help':
            args.pop(0)
            args.append('--help')
        commands.gyrobot.main(args=args,
                              prog_name=trigger_words[0],
                              standalone_mode=False,
                              obj={
                                  'chat': chat_obj,
                                  'logger': logger,
                                  'stdout': real_stdout,
                                  'stderr': real_stderr,
                                  'subreddit': subreddit,
                                  'reddit_session': reddit_session,
                                  'bot_reddit_session': bot_reddit_session
                              })

        postcmd()
    except Exception as e:
        if 'DEBUG' in os.environ:
            exception_full_text = ''.join(traceback.format_exception(*sys.exc_info()))
            error_text = f"```\n:::Error:::\n{exception_full_text}```\n"
        else:
            error_text = f"```\n:::Error:::\n{e}```\n"
        # noinspection PyBroadException
        try:
            chat_obj.send_text(error_text, is_error=True)
        except Exception as e:
            logger.critical('Could not send exception error: ' + error_text)


IDENTCHARS = string.ascii_letters + string.digits + '_'


def precmd(line):
    i, n = 0, len(line)
    while i < n and line[i] in IDENTCHARS: i += 1
    return line[:i].lower() + line[i:]


def postcmd():
    global stdout
    stdout.flush()
    stdout.seek(0, io.SEEK_SET)
    text = stdout.read()
    stdout.close()
    stdout = io.StringIO()
    sys.stdout = sys.stderr = stdout

    # self.pos = self.stdout.seek(0, io.SEEK_CUR)
    if text != '':
        chat_obj.send_text('```\n' + text.strip() + '```\n')


def default(line):
    instant_answer_page = requests.get("https://api.duckduckgo.com/", params={'q': line, "format": "json"})
    instant_answer = instant_answer_page.json()
    # self._send_file(instant_answer_page.content, filename='duckduckgo.json', filetype='application/json')
    if isinstance(instant_answer["Answer"], str) and instant_answer["Answer"]:
        chat_obj.send_text(instant_answer["Answer"])
        if 'Image' in instant_answer:
            chat_obj.send_text(instant_answer['Image'])
    elif instant_answer["AbstractText"]:
        chat_obj.send_text(instant_answer["AbstractText"])
        if 'Image' in instant_answer:
            chat_obj.send_text(instant_answer['Image'])
    elif instant_answer['RelatedTopics']:
        topic = instant_answer['RelatedTopics'][0]
        chat_obj.send_text(topic['Text'])
        if 'Icon' in topic:
            chat_obj.send_text(topic['Icon']['URL'])
    else:
        chat_obj.send_text(
            f"```I don't know what to do with {line}.\nTry one of the following commands:\n```",
            is_error=True)
        do_help('')


def emptyline():
    chat_obj.send_text("```You need to provide a command. Try these:```\n", is_error=True)
    do_help('')


def main():
    global chat_obj, logger
    global subreddit_name, subreddit, reddit_session, bot_reddit_session
    global trigger_words, shortcut_words
    logger = setup_logging(os.environ.get('LOG_NAME', 'unknown'))
    sys.excepthook = excepthook
    init()
    slack_client.start()


if __name__ == '__main__':
    main()
