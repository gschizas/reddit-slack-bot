from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML(typ='safe')
_yaml.default_flow_style = False
_out = Path('config') / 'flair-bot.yml'


def write_config(cfg):
    _yaml.dump(cfg, _out)


def read_config():
    return _yaml.load(_out)
