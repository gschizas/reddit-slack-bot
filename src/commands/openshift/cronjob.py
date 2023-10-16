import json
import pathlib

import click
from ruamel.yaml import YAML

from commands import gyrobot, chat
from commands.openshift.api import get_cronjobs, change_cronjob_suspend_state
from commands.openshift.common import read_config, OpenShiftNamespace, check_security

yaml = YAML()
REMOVE_CRONJOB_KEYS = ['Containers', 'Images', 'Selector']
_cronjob_config = read_config('OPENSHIFT_CRONJOB')
_data_file = pathlib.Path('data') / 'cronjob-stack.yml'
if not _data_file.exists():
    _data_file.write_text('')


@gyrobot.group('cronjob')
@click.pass_context
def cronjob(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _cronjob_config
    ctx.obj['security_text'] = {'list': 'list cronjobs', 'pause': 'pause cronjobs', 'resume': 'resume cronjobs'}


@cronjob.command('list')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def list_cronjobs(ctx: click.Context, namespace: str, excel: bool):
    cronjobs = get_cronjobs(ctx, namespace)
    if not excel:
        cronjobs = [{k: v for k, v in cronjob.items() if k not in REMOVE_CRONJOB_KEYS} for cronjob in cronjobs]
    chat(ctx).send_table(title='cronjobs', table=cronjobs, send_as_excel=excel)


@cronjob.command('pause')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.pass_context
@check_security
def pause_cronjob(ctx: click.Context, namespace: str):
    cronjobs = get_cronjobs(ctx, namespace)
    with open('data/cronjob-stack.yml', mode='r', encoding='utf8') as f:
        suspended_cronjobs_stack = yaml.load(f) or []
    suspended_cronjobs = []
    result = []
    for one_cronjob in cronjobs:
        if one_cronjob['Suspend']:
            continue
        suspended_cronjobs.append(one_cronjob['Name'])
        result.append(change_cronjob_suspend_state(ctx, namespace, one_cronjob['Name'], True))
    suspended_cronjobs_stack.append(suspended_cronjobs)
    with open('data/cronjob-stack.yml', mode='w', encoding='utf8') as f:
        yaml.dump(suspended_cronjobs_stack, f)
    chat(ctx).send_file(json.dumps(result).encode(), filename='cronjobs.json')


@cronjob.command('resume')
@click.argument('namespace', type=OpenShiftNamespace(_cronjob_config))
@click.pass_context
@check_security
def resume_cronjob(ctx: click.Context, namespace):
    with open('data/cronjob-stack.yml', mode='r', encoding='utf8') as f:
        suspended_cronjobs_stack = yaml.load(f) or []
    if len(suspended_cronjobs_stack) == 0:
        chat(ctx).send_text("No cronjobs to resume", is_error=True)
        return
    cronjobs_to_resume = suspended_cronjobs_stack.pop() or []
    result = []
    for one_cronjob_name in cronjobs_to_resume:
        result.append(change_cronjob_suspend_state(ctx, namespace, one_cronjob_name, False))
    with open('data/cronjob-stack.yml', mode='w', encoding='utf8') as f:
        yaml.dump(suspended_cronjobs_stack, f)
    chat(ctx).send_file(json.dumps(result).encode(), filename='cronjobs.json')
