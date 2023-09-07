import re
import subprocess
from string import Template

import click
from ruamel.yaml import YAML

from commands import gyrobot, chat, DefaultCommandGroup
from commands.openshift.common import OpenShiftNamespace, azure_login, check_security, read_config

yaml = YAML()


def _mock_config():
    config = read_config('MOCK_CONFIGURATION')
    default_environment = config.get('default_environment', {})
    for env_name, env in config['environments'].items():
        if 'status' not in env:
            env['status'] = default_environment['status']
        for status, microservice_vars in env['status'].items():
            env['status'][status] = default_environment.get('status', {}).get(status, {}) | microservice_vars
        env['vartemplate'] = env.get('vartemplate', {}) | default_environment.get('vartemplate', {})
    return config


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


def _get_project_name(env_config, environment):
    project_name = env_config.get('projectNameOverride', environment.lower())
    project_prefix = env_config.get('projectPrefix')
    if project_prefix:
        project_name = project_prefix + '-' + project_name
    return project_name


@gyrobot.group('mock', cls=DefaultCommandGroup)
@click.pass_context
def mock(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _mock_config()
    ctx.obj['security_text'] = {'set': 'switch mock status', 'check': 'view mock status'}


@mock.command(default_command=True,
              context_settings={
                  'ignore_unknown_options': True,
                  'allow_extra_args': True})
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.argument('mock_status')
@click.pass_context
def mock_default(ctx: click.core.Context, namespace: str, mock_status: OpenShiftNamespace):
    ctx.forward(set_mock)


@mock.command('set')
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.argument('mock_status')
@click.pass_context
@check_security
def set_mock(ctx, namespace: str, mock_status: str):
    """Switch openshift mock status on environment"""
    mock_config = ctx.obj['config']
    env_vars = mock_config['env_vars']
    env_config = mock_config['environments'][namespace]
    valid_mock_statuses = [k.upper() for k in env_config['status'].keys()]
    mock_status = mock_status.upper()
    if mock_status not in valid_mock_statuses:
        chat(ctx).send_text((f"Invalid status `{mock_status}`. "
                             f"Mock status must be one of {', '.join(valid_mock_statuses)}"), is_error=True)
        return

    result_text = ""
    site = env_config['site']
    prefix = env_config['prefix']
    project_name = _get_project_name(env_config, namespace)

    if site == 'azure':
        result_text += azure_login(
            ctx,
            env_config['credentials']['servicePrincipalId'],
            env_config['credentials']['servicePrincipalKey'],
            env_config['credentials']['tenantId'],
            env_config['azure_resource_group'],
            env_config['azure_cluster_name'])
    else:
        oc_token = env_config['credentials']
        login_cmd = subprocess.run(['oc', 'login', site, f'--token={oc_token}'], capture_output=True)
        login_result = login_cmd.stderr.decode().strip()
        if login_cmd.returncode != 0:
            chat(ctx).send_text(f"Error while logging in:\n```{login_result}```", is_error=True)
            return
        result_text += login_result + '\n' * 3
        change_project_command = ['oc', 'project', project_name]
        result_text += subprocess.check_output(change_project_command).decode() + '\n' * 3

    statuses = env_config['status'][mock_status]
    vartemplates = env_config.get('vartemplate', {})
    if _check_recursive(ctx, vartemplates):
        return

    chat(ctx).send_text(f"Setting mock status to {mock_status} for project {project_name} on {namespace}...")

    for microservice_info, status in statuses.items():
        microservice, env_variable_value = _get_environment_values(env_vars, vartemplates, microservice_info, status)
        environment_set_args = ['oc', 'set', 'env', prefix + microservice, env_variable_value]
        if site == 'azure':
            environment_set_args.extend(['-n', project_name])
        environment_set_cmd = subprocess.run(environment_set_args, capture_output=True)
        if environment_set_cmd.returncode:
            result_text += environment_set_cmd.stderr.decode() + '\n\n'
        result_text += environment_set_cmd.stdout.decode() + '\n\n'

    if site != 'azure':
        logout_command = ['oc', 'logout']
        result_text += subprocess.check_output(logout_command).decode() + '\n\n'
        result_text = re.sub('\n{2,}', '\n', result_text)
    # chat(ctx).send_text('```' + result_text + '```')

    chat(ctx).send_file(result_text.encode(), filename='mock.txt')


def _check_recursive(ctx, vartemplates):
    """Check that variables don't contain themselves"""
    for name, value in vartemplates.items():
        if '$' + name in value:
            chat(ctx).send_text(
                f"Recursive variable template: `{value}` contains `{name}`. ",
                is_error=True)
            return True
    return False


def _get_environment_values(env_vars, vartemplates, microservice_info, status):
    if '$' not in microservice_info: microservice_info += '$'
    microservice, env_var_shortcut = microservice_info.split('$')
    env_var_name: str = env_vars[env_var_shortcut]
    env_variable_value = f'{env_var_name}={status}' if status is not None else f'{env_var_name}-'
    while '$' in env_variable_value:
        env_variable_value = Template(env_variable_value).substitute(**vartemplates)
    return microservice, env_variable_value


@mock.command('check')
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.pass_context
@check_security
def mock_check(ctx, namespace):
    """View current status of environment"""
    env_config = ctx.obj['config']['environments'][namespace]
    oc_token = env_config['credentials']
    site = env_config['site']
    result_text = subprocess.check_output(['oc', 'login', site, f'--token={oc_token}']).decode() + '\n' * 3
    prefix = env_config['prefix']
    project_name = _get_project_name(env_config, namespace)
    result_text += subprocess.check_output(['oc', 'project', project_name]).decode() + '\n' * 3
    first_status = list(env_config['status'].keys())[0]
    microservices = list(env_config['status'][first_status].keys())
    for microservice in microservices:
        env_var_list = subprocess.check_output(['oc', 'set', 'env', prefix + microservice, '--list']).decode()
        env_var_list = _masked_oc_password(env_var_list)
        result_text += env_var_list + '\n\n'
    result_text += subprocess.check_output(['oc', 'logout']).decode() + '\n\n'
    chat(ctx).send_file(result_text.encode(), title='OpenShift Data', filename='openshift-data.txt')
