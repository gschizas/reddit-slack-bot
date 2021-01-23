#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import traceback

import slackclient

from bot_framework.common import setup_logging
from bot_framework.praw_wrapper import praw_wrapper
from bot_framework.yaml_wrapper import yaml
from command_shell import SlackbotShell

shell: SlackbotShell = None
logger = None


def init():
    global shell, logger
    shell = SlackbotShell()
    slack_api_token = os.environ['SLACK_API_TOKEN']
    shell.subreddit_name = os.environ.get('SUBREDDIT_NAME')
    shell.sc = slackclient.SlackClient(slack_api_token)
    shell.logger = logger
    if shell.subreddit_name:
        base_user_agent = 'python:gr.terrasoft.reddit.slackmodbot'
        user_agent = f'{base_user_agent}-{shell.subreddit_name}:v0.2 (by /u/gschizas)'
        shell.reddit_session = praw_wrapper(user_agent=user_agent, scopes=['*'])
        if 'REDDIT_ALT_USER' in os.environ:
            alt_user = os.environ['REDDIT_ALT_USER']
            alt_user_agent = f'{base_user_agent}-{shell.subreddit_name}-as-{alt_user}:v0.2 (by /u/gschizas)'
            shell.bot_reddit_session = praw_wrapper(user_agent=alt_user_agent,
                                                    prompt=f'Visit the following URL as {alt_user}:',
                                                    scopes=['*'])


def excepthook(type_, value, tb):
    global shell
    global logger
    # noinspection PyBroadException
    try:
        logger.fatal(type_, value, tb, exc_info=True)
        if shell:
            # noinspection PyBroadException
            try:
                error_text = f"```\n:::Error:::\n{value!r}```\n"
            except Exception:
                error_text = "???"
            shell._send_text(error_text, is_error=True)
    except Exception:
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
        del SlackbotShell.do_undo_nuke_thread
        del SlackbotShell.do_nuke_user
        del SlackbotShell.do_usernotes
        del SlackbotShell.do_youtube_info
        del SlackbotShell.do_history
        del SlackbotShell.do_comment_source
        del SlackbotShell.do_deleted_comment_source
        del SlackbotShell.do_allow_only_regulars
        del SlackbotShell.do_order_66
        del SlackbotShell.do_order66
        del SlackbotShell.do_configure_enhanched_crowd_control

    if not shell.bot_reddit_session:
        del SlackbotShell.do_make_post
        del SlackbotShell.do_make_sticky

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
                shell.handle_message(msg)
            time.sleep(0.5)
        except Exception as ex:  # slackclient.server.SlackConnectionResetError as ex:
            tb = sys.exc_info()[2]
            logger.warning(''.join(traceback.format_exception(None, ex, tb)))
            if shell.sc.rtm_connect():
                logger.info("Connection established")
            else:
                logger.critical("Connection failed. Waiting 5 seconds")
                time.sleep(5)


if __name__ == '__main__':
    main()
