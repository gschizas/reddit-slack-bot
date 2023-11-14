import os
import pathlib
from contextlib import contextmanager

from bot_framework.yaml_wrapper import yaml


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
