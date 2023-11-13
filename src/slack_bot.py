#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import concurrent.futures
import locale
import logging
import os
import re
import traceback

import click.testing
import praw
import requests

import commands
import commands.convert
import commands.generic
import commands.weather
from bot_framework.common import normalize_text
from bot_framework.common import setup_logging
from bot_framework.praw_wrapper import praw_wrapper
from bot_framework.yaml_wrapper import yaml
from chat import get_chat_wrapper, ChatWrapper

locale.setlocale(locale.LC_ALL, os.environ.get('LOCALE', ''))

if 'MOCK_CONFIGURATION' in os.environ:
    import commands.openshift.mock

if 'DOCKER_DEPLOY_CONFIGURATION' in os.environ:
    import commands.openshift.docker_deploy

if 'OPENSHIFT_ACTUATOR_REFRESH' in os.environ:
    import commands.openshift.refresh_actuator

if 'OPENSHIFT_SCALEDOWN' in os.environ:
    import commands.openshift.scaledown

if 'OPENSHIFT_DEPLOYMENT' in os.environ:
    import commands.openshift.deployment

if 'OPENSHIFT_CRONJOB' in os.environ:
    import commands.openshift.cronjob

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

if 'GYROBOT_DATABASE_URL' in os.environ:
    import commands.reddit.database

logger: logging.Logger
chat_obj: ChatWrapper
reddit_session: praw.Reddit = None
bot_reddit_session: praw.reddit.Reddit = None
subreddit: praw.reddit.Subreddit = None
subreddit_name: str
trigger_words: list
shortcut_words: dict
bot_name: str
runner: click.testing.CliRunner
executor: concurrent.futures.ThreadPoolExecutor


def init():
    global chat_obj, logger, subreddit_name, shortcut_words, bot_name, trigger_words, executor
    global reddit_session, bot_reddit_session, subreddit
    global runner
    runner = click.testing.CliRunner()
    runner.mix_stderr = True
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

    trigger_words = os.environ['BOT_NAME'].split()
    bot_name = trigger_words[0]
    logger.debug(f"Listening for {','.join(trigger_words)}")
    if 'SHORTCUT_WORDS' in os.environ:
        with open('data/' + os.environ['SHORTCUT_WORDS']) as sf:
            shortcut_words = dict(yaml.load(sf))
    else:
        shortcut_words = {}

    chat_obj = get_chat_wrapper(trigger_words[0], handle_message)
    chat_obj.connect()

    subreddit_name = os.environ.get('SUBREDDIT_NAME')
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

    text_lines = parse_shortcuts(msg['text'])
    for text_line in text_lines:
        handle_line(text_line)


def parse_shortcuts(text):
    global shortcut_words
    text_lines = [text]
    typed_text = normalize_text(text).strip().lower().split()
    if not typed_text:
        return []
    first_word = typed_text[0]
    if first_word in shortcut_words:
        replaced_words = shortcut_words[first_word]
        if all([isinstance(w, str) for w in replaced_words]):  # shortcut definition is a list of all strings
            typed_text = replaced_words + typed_text[1:]
            first_word = typed_text[0]
            text = ' '.join(replaced_words) + ' ' + ' '.join(text.split()[1:])
            text_lines = [text]
        elif all([type(w) is list for w in replaced_words]) and \
                all([all([isinstance(ww, str) for ww in w]) for w in replaced_words]):
            # shortcut definition is a list of lists and each of them is a list of strings
            first_word = replaced_words[0][0]
            text_lines = [' '.join(replaced_words_line) for replaced_words_line in replaced_words]
        else:
            logger.critical(f'Bad format for shortcut {first_word}')
    if not any([first_word == trigger_word for trigger_word in trigger_words]):
        return []
    return text_lines


def handle_line(text):
    global chat_obj, trigger_words
    logger.debug(f"Triggerred by {text}")
    line = ' '.join(text.split()[1:])
    line = precmd(line)
    args = line.split()
    if args[0].lower() == 'help':
        args.pop(0)
        args.append('--help')
    commands.gyrobot.name = trigger_words[0]
    context_obj = {
        'chat': chat_obj,
        'logger': logger,
        'subreddit': subreddit,
        'reddit_session': reddit_session,
        'bot_reddit_session': bot_reddit_session
    }
    executor.submit(run_command, runner, args, context_obj)


def run_command(runner, args, context_obj):
    result = runner.invoke(commands.gyrobot, args=args, obj=context_obj, catch_exceptions=True)
    if result.exception:
        if 'DEBUG' in os.environ:
            error_text = ''.join(traceback.format_exception(*result.exc_info))
        elif 'PERSONAL_DEBUG' in os.environ:
            error_text = str(result.exception)
            exception_full_text = ''.join(traceback.format_exception(*result.exc_info))
            chat_obj.send_file(filename='error.txt', file_data=exception_full_text.encode(),
                               channel=os.environ['PERSONAL_DEBUG'])
        else:
            error_text = str(result.exception)
        if len(error_text) < 2 ** 11:
            chat_obj.send_text(f"```\n:::Error:::{error_text}```\n", is_error=True)
        else:
            chat_obj.send_file(filename='error.txt', file_data=error_text.encode())

    if result.output != '':
        chat_obj.send_text('```\n' + result.output.strip() + '```\n')


def precmd(line):
    """Convert the beginning part of the input string line to lowercase.
    The “beginning part” is defined as the longest prefix composed only of alphanumeric characters and underscores.
    The rest of the string will remain unchanged."""
    match = re.match('^[_A-Za-z0-9]*', line)
    if match:
        matched_part = match.group(0)
        return matched_part.lower() + line[len(matched_part):]
    else:
        return line


def default(line):
    instant_answer_page = requests.get("https://api.duckduckgo.com/", params={'q': line, "format": "json"})
    instant_answer = instant_answer_page.json()
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


def main():
    global chat_obj, logger
    global subreddit_name, subreddit, reddit_session, bot_reddit_session
    global trigger_words, shortcut_words
    logger = setup_logging(os.environ.get('LOG_NAME', 'unknown'), when=os.environ.get('LOG_ROLLOVER'))
    init()
    chat_obj.start()


if __name__ == '__main__':
    main()
