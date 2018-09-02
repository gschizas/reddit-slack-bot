import logging
import logging.handlers
import os
import os.path
import sys


def setup_logging(extra_name=None):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if extra_name:
        extra_name = '-' + extra_name

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if not os.path.exists('logs'):
        os.mkdir('logs')

    filename = os.path.basename(sys.argv[0])
    basename = os.path.splitext(filename)[0]

    fh = logging.handlers.TimedRotatingFileHandler(f'logs/{filename}{extra_name}.log', when='W0')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def change_to_local_dir():
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)
