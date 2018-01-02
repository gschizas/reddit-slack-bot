import logging
import os
import os.path


def setup_logging():
    global logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    if not os.path.exists('logs'):
        os.mkdir('logs')

    filename = os.path.basename(__file__)
    basename = os.path.splitext(filename)[0]

    fh = logging.handlers.TimedRotatingFileHandler(f'logs/{filename}.log', when='W0')
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)


def change_to_local_dir():
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)
