import logging
import logging.handlers
import os
import os.path
import sys

import colorlog
import requests


def setup_logging(extra_name=None, disable_tty=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if extra_name:
        extra_name = '-' + extra_name
    else:
        extra_name = ''


    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if not os.path.exists('logs'):
        os.mkdir('logs')

    filename = os.path.basename(sys.argv[0])
    basename = os.path.splitext(filename)[0]

    if sys.stdout.isatty() and not disable_tty:
        ch = colorlog.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(colorlog.ColoredFormatter('%(log_color)s%(levelname)s\t%(name)s\t%(message)s'))
        logger.addHandler(ch)

    fh = logging.handlers.TimedRotatingFileHandler(f'logs/{basename}{extra_name}.log', when='W0')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    fh2 = logging.handlers.TimedRotatingFileHandler(f'logs/{basename}{extra_name}.debug.log', when='W0')
    fh2.setLevel(logging.DEBUG)
    fh2.setFormatter(formatter)
    logger.addHandler(fh2)

    return logger


def change_to_local_dir():
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)


def send_to_slack(url, channel, title, main_text, color, username, emoji, logger):
    payload = {
        'channel': channel,
        'username': username,
        'color': color,
        'unfurl_links': True,
        'pretext': title,
        'icon_emoji': emoji,
        'text': main_text
    }
    doit = requests.post(url, json=payload)
    logger.debug(doit)
    logger.debug(doit.text)
