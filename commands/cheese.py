import json
import os

import click
import psycopg2

from bot_framework.yaml_wrapper import yaml
from commands import gyrobot, chat

config = None


def __init__():
    global config
    config = _config()


def _config():
    with open('data/cheese_agent.yml') as f:
        return yaml.load(f)


def _cheese_db_view(sql_cmd, cmd_vars):
    return _cheese_db_query(sql_cmd, cmd_vars, get_rows=True)


def _cheese_db_exec(sql_cmd, cmd_vars):
    return _cheese_db_query(sql_cmd, cmd_vars, get_rows=False)


def _cheese_db_query(sql_cmd, cmd_vars, get_rows: bool):
    rows = None
    success = False
    database_url = os.environ['CHEESE_DATABASE_URL']
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql_cmd, vars=cmd_vars)
    if get_rows:
        descr = [col.name for col in cur.description]
        rows = cur.fetchall()
    else:
        success = cur.rowcount > 0
    cur.close()
    conn.close()
    if get_rows:
        return [dict(zip(descr, row)) for row in rows]
    else:
        return success


@gyrobot.group('cheese')
def cheese():
    """Cheese Service Agent"""
    pass


@cheese.group('ngrok')
def ngrok(ctx):
    pass


@ngrok.command('status')
@click.pass_context
def ngrok_status(ctx):
    for setup_info in config['setup']:
        if chat(ctx).user_id in setup_info['slack_ids']:
            computer_name = setup_info['computer_name']
            rows = _cheese_db_view(SQL_CHEESE_VIEW, {'machine_name': computer_name})

            if rows:
                payload = rows[0]['objectData']
                last_update = rows[0]['lastUpdate']
                ngrok_address = payload['ngrok']['tunnels'][0]['public_url']
                result_fields.append(f"*{computer_name}*: {ngrok_address}")
                result_fields.append(f"Last update: {last_update:%a %d %b %Y %H:%M:%S}")
    if result_fields:
        result_blocks = [{
            "type": "section",
            "fields": [{"type": "mrkdwn", "text": result_field} for result_field in result_fields]
        }]
        chat(ctx).send_ephemeral(blocks=result_blocks)
    else:
        chat(ctx).send_text("No Data", is_error=True)


@ngrok.command('restart')
@click.argument('computer')
def ngrok_restart(computer):
    computer_name = computer
    job_data = dict(kind='ngrok_restart', machine=computer_name)
    _cheese_add_to_queue(job_data, computer_name=computer_name)


@cheese.group('citrix')
def citrix():
    pass


@citrix.command('restart')
@click.argument('computer')
def citrix_restart(computer):
    job_data = dict(kind='citrix_restart', machine=computer)
    _cheese_add_to_queue(job_data, computer_name=computer)


@citrix.command('status')
@click.argument('computer')
@click.pass_context
def citrix_status(ctx, computer):
    result_blocks = []
    for setup_info in config['setup']:
        if chat(ctx).user_id in setup_info['slack_ids']:
            computer_name = setup_info['computer_name']
            rows = _cheese_db_view(SQL_CHEESE_VIEW, {'machine_name': computer_name})

            if rows:
                payload = rows[0]['objectData']
                last_update = rows[0]['lastUpdate']
                result_blocks.append({
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Citrix Services Status for {computer_name}"}})
                result_blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain_text",
                            "text": f"Last Update: {last_update:%a %d %b %Y %H:%M:%S}"
                        }
                    ]
                })
                services_info = payload['citrix_services_info']
                for si in services_info:
                    status_emoji = {
                        'SERVICE_STOPPED': 'x',
                        'SERVICE_START_PENDING': 'black_right_pointing_triangle_with_double_vertical_bar',
                        'SERVICE_STOP_PENDING': 'black_square_for_stop',
                        'SERVICE_RUNNING': 'white_check_mark',
                        'SERVICE_CONTINUE_PENDING': 'arrow_double_up',
                        'SERVICE_PAUSE_PENDING': 'arrow_double_down',
                        'SERVICE_PAUSED': 'double_vertical_bar'}.get(si['Status']['CurrentState'], 'question')
                    result_blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":{status_emoji}: {si['ShortName']} ({si['Description']})"
                        }
                    })
    if result_blocks:
        chat(ctx).send_ephemeral(blocks=result_blocks)


@cheese.command('message')
@click.argument('computer', nargs=1)
@click.argument('message', nargs=-1)
@click.pass_context
def message(ctx, computer, message):
    message_text = ' '.join(message)
    _cheese_add_to_queue(dict(kind='message', text=message_text), computer_name=computer)
    chat(ctx).send_ephemeral(f"Restaring {computer} citrix services")


def _cheese_add_to_queue(self, job_data, computer_name=None):
    for setup_info in config['setup']:
        if self.user_id in setup_info['slack_ids']:
            a_computer_name = setup_info['computer_name']
            if computer_name:
                if a_computer_name.lower() != computer_name.lower():
                    continue
            _cheese_db_exec(SQL_CHEESE_QUEUE_ADD, {
                'machine_name': a_computer_name,
                'job_data': json.dumps(job_data)
            })


SQL_CHEESE_VIEW = """SELECT "objectData", "lastUpdate" FROM "machineState" WHERE "machineState"."machineName" = %(machine_name)s;"""
SQL_CHEESE_QUEUE_ADD = """\
INSERT INTO public."jobQueue"(
    "machineName", "jobData")
    VALUES (%(machine_name)s, %(job_data)s);
"""
