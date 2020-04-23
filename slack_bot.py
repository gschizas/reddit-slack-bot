#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import traceback

import slackclient

from bot_framework.common import setup_logging, normalize_text
from bot_framework.praw_wrapper import praw_wrapper
from bot_framework.yaml_wrapper import yaml
from command_shell import SlackbotShell


def init():
    global shell, logger
    shell = SlackbotShell()
    slack_api_token = os.environ['SLACK_API_TOKEN']
    shell.subreddit_name = os.environ.get('SUBREDDIT_NAME')
    shell.sc = slackclient.SlackClient(slack_api_token)
    shell.logger = logger
    if shell.subreddit_name:
        user_agent = f'python:gr.terrasoft.reddit.slackmodbot-{shell.subreddit_name}:v0.1 (by /u/gschizas)'
        shell.reddit_session = praw_wrapper(user_agent=user_agent, scopes=['*'])


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
    global logger, shell
    logger = setup_logging(os.environ.get('LOG_NAME', 'unknown'))
    sys.excepthook = excepthook
    init()

    if shell.sc.rtm_connect():
        logger.info('Connection established')
    else:
        logger.critical('Connection failed')
        sys.exit(1)

    # Disable features according to environment

    if not shell.subreddit_name:
        del SlackbotShell.do_add_domain_tag
        del SlackbotShell.do_add_policy
        del SlackbotShell.do_archive_user
        del SlackbotShell.do_modqueue_comments
        del SlackbotShell.do_modqueue_posts
        del SlackbotShell.do_nuke_thread
        del SlackbotShell.do_nuke_user
        del SlackbotShell.do_usernotes
        del SlackbotShell.do_youtube_info
        del SlackbotShell.do_history
        del SlackbotShell.do_comment_source
        del SlackbotShell.do_deleted_comment_source

    if 'QUESTIONNAIRE_DATABASE_URL' not in os.environ or 'QUESTIONNAIRE_FILE' not in os.environ:
        del SlackbotShell.do_survey

    if 'KUDOS_DATABASE_URL' not in os.environ:
        del SlackbotShell.do_kudos

    if 'MOCK_CONFIGURATION' not in os.environ:
        del SlackbotShell.do_mock
        del SlackbotShell.do_check_mock

    if shell.subreddit_name:
        shell.sr = shell.reddit_session.subreddit(shell.subreddit_name)
    shell.trigger_words = os.environ['BOT_NAME'].split()
    if 'SHORTCUT_WORDS' in os.environ:
        with open('data/' + os.environ['SHORTCUT_WORDS']) as sf:
            shell.shortcut_words = dict(yaml.load(sf))
    else:
        shell.shortcut_words = {}
    logger.debug(f"Listening for {','.join(shell.trigger_words)}")

    while True:
        try:
            for msg in shell.sc.rtm_read():
                handle_message(msg)
            time.sleep(0.5)
        except Exception as ex:  # slackclient.server.SlackConnectionResetError as ex:
            tb = sys.exc_info()[2]
            logger.warning(''.join(traceback.format_exception(None, ex, tb)))
            if shell.sc.rtm_connect():
                logger.info("Connection established")
            else:
                logger.critical("Connection failed. Waiting 5 seconds")
                time.sleep(5)


def handle_message(msg):
    global shell, logger
    if msg['type'] != 'message':
        logger.debug(f"Found message of type {msg['type']}")
        return
    if msg.get('subtype') in ('message_deleted', 'file_share', 'bot_message', 'slackbot_response'):
        logger.debug(f"Found message of subtype {msg.get('subtype')}")
        return
    if 'message' in msg:
        msg.update(msg['message'])
        del msg['message']

    channel_id = msg['channel']
    team_id = msg.get('team', '')
    user_id = msg.get('user', '')

    permalink = shell.sc.api_call('chat.getPermalink', channel=channel_id, message_ts=msg['ts'])
    shell.preload(user_id, team_id, channel_id)

    text = msg['text']

    typed_text = normalize_text(text).strip().lower().split()
    if not typed_text:
        return
    first_word = typed_text[0]
    if first_word in shell.shortcut_words:
        replaced_words = shell.shortcut_words[first_word]
        typed_text = replaced_words + typed_text[1:]
        first_word = typed_text[0]
        text = ' '.join(replaced_words) + ' ' + ' '.join(text.split()[1:])
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


if __name__ == '__main__':
    main()
