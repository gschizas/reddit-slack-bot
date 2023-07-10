import json
import os
import pathlib
import re
import subprocess
from string import Template

import click

from commands import gyrobot, chat
from commands.openshift.common import OpenShiftNamespace, check_security

def _mock_config():
    if os.environ['MOCK_CONFIGURATION'].startswith('/'):
        config_file = pathlib.Path(os.environ['MOCK_CONFIGURATION'])
    else:
        config_file = pathlib.Path('config') / os.environ['MOCK_CONFIGURATION']
    with config_file.open() as f:
        mock_config = json.load(f)
    with config_file.with_suffix('.credentials.json').open() as f:
        credentials = json.load(f)
    for env in mock_config['environments']:
        if env in credentials:
            mock_config['environments'][env]['openshift_token'] = credentials[env]
    default_environment = mock_config.get('default_environment', {})
    for env_name, env in mock_config['environments'].items():
        if 'status' not in env:
            env['status'] = default_environment['status']
        for status, microservice_vars in env['status'].items():
            env['status'][status] = default_environment.get('status', {}).get(status, {}) | microservice_vars
        env['vartemplate'] = env.get('vartemplate', {}) | default_environment.get('vartemplate', {})
        for key, value in default_environment.items():
            if key in ('status', 'vartemplate'): # we have already handled these
                continue
            if key in env: # value already exists
                continue
    return mock_config


def _masked_oc_password(variable_list):
    variables = variable_list.splitlines()
    result = ""
    for full_variable in variables:
        if full_variable.startswith('#') or full_variable == '':
            result += full_variable + '\n'
        else:
            variable_name, variable_value = full_variable.split('=', 1)
            if 'password' in variable_name.lower() or 'auth_header_value' in variable_name.lower():
                result += variable_name + '=' + variable_value[:2] + 9 * '*' + variable_value[-2:] + '\n'
            else:
                result += full_variable + '\n'
    return result


def _get_project_name(mock_config, environment):
    project_name = mock_config['environments'][environment].get('projectNameOverride', environment.lower())
    project_prefix = mock_config['environments'][environment].get('projectPrefix')
    if project_prefix:
        project_name = project_prefix + '-' + project_name
    return project_name


@gyrobot.command('mock')
@click.argument('environment', type=OpenShiftNamespace(_mock_config()['environments'], force_upper=True))
@click.argument('mock_status')
@click.pass_context
def mock(ctx, environment, mock_status):
    """Switch openshift mock status on environment"""
    mock_config = _mock_config()
    if chat(ctx).user_id not in mock_config['allowed_users']:
        chat(ctx).send_text(f"You don't have permission to switch mock status.", is_error=True)
        return
    mock_status = mock_status.upper()
    env_vars = mock_config['env_vars']
    valid_mock_statuses = [k.upper() for k in mock_config['environments'][environment]['status'].keys()]
    if mock_status not in valid_mock_statuses:
        chat(ctx).send_text((f"Invalid status `{mock_status}`. "
                             f"Mock status must be one of {', '.join(valid_mock_statuses)}"), is_error=True)
        return

    oc_token = mock_config['environments'][environment]['openshift_token']
    site = mock_config['environments'][environment]['site']
    login_cmd = subprocess.run(['oc', 'login', site, f'--token={oc_token}'], capture_output=True)
    login_result = login_cmd.stderr.decode().strip()
    if login_cmd.returncode != 0:
        chat(ctx).send_text(f"Error while logging in:\n```{login_result}```", is_error=True)
        return
    result_text = login_result + '\n' * 3
    prefix = mock_config['environments'][environment]['prefix']
    chat(ctx).send_text(f"Setting mock status to {mock_status} for project {environment}...")
    project_name = _get_project_name(mock_config, environment)
    change_project_command = ['oc', 'project', project_name]
    result_text += subprocess.check_output(change_project_command).decode() + '\n' * 3
    statuses = mock_config['environments'][environment]['status'][mock_status]
    vartemplates = mock_config['environments'][environment].get('vartemplate', {})
    for name, value in vartemplates.items(): # check that there's no recursive loop
        if '$' + name in value:
            chat(ctx).send_text(
                f"Recursive variable template: `{value}` contains `{name}`. ",
                is_error=True)
            return

    for microservice_info, status in statuses.items():
        if '$' not in microservice_info: microservice_info += '$'
        microservice, env_var_shortcut = microservice_info.split('$')
        env_var_name: str = env_vars[env_var_shortcut]
        env_variable_value = f'{env_var_name}={status}' if status is not None else f'{env_var_name}-'
        while '$' in env_variable_value:
            env_variable_value = Template(env_variable_value).substitute(**vartemplates)
        environment_set_command = ['oc', 'set', 'env', prefix + microservice, env_variable_value]
        result_text += subprocess.check_output(environment_set_command).decode() + '\n\n'
    logout_command = ['oc', 'logout']
    result_text += subprocess.check_output(logout_command).decode() + '\n\n'
    result_text = re.sub('\n{2,}', '\n', result_text)
    chat(ctx).send_text('```' + result_text + '```')


@gyrobot.command('check_mock')
@click.argument('environment', type=OpenShiftNamespace(_mock_config()['environments'], force_upper=True))
@click.pass_context
def check_mock(ctx, environment):
    """View current status of environment"""
    mock_config = _mock_config()
    if chat(ctx).user_id not in mock_config['allowed_users']:
        chat(ctx).send_text(f"You don't have permission to view mock status.", is_error=True)
    oc_token = mock_config['environments'][environment]['openshift_token']
    site = mock_config['environments'][environment]['site']
    result_text = subprocess.check_output(['oc', 'login', site, f'--token={oc_token}']).decode() + '\n' * 3
    prefix = mock_config['environments'][environment]['prefix']
    project_name = _get_project_name(mock_config, environment)
    result_text += subprocess.check_output(['oc', 'project', project_name]).decode() + '\n' * 3
    first_status = list(mock_config['environments'][environment]['status'].keys())[0]
    microservices = list(mock_config['environments'][environment]['status'][first_status].keys())
    for microservice in microservices:
        env_var_list = subprocess.check_output(['oc', 'env', prefix + microservice, '--list']).decode()
        env_var_list = _masked_oc_password(env_var_list)
        result_text += env_var_list + '\n\n'
    result_text += subprocess.check_output(['oc', 'logout']).decode() + '\n\n'
    chat(ctx).send_file(result_text.encode(), title='OpenShift Data', filename='openshift-data.txt')
