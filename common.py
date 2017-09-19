from ruamel import yaml


def write_config(cfg):
    with open('config/flair-bot.yml', encoding='utf8', mode='w') as fp:
        yaml.safe_dump(cfg, fp, default_flow_style=False)


def read_config():
    with open('config/flair-bot.yml', encoding='utf8', mode='r') as fp:
        cfg = yaml.safe_load(fp)
    return cfg
