import subprocess
from string import Template

import click
from ruamel.yaml import YAML

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext
from commands.openshift.common import OpenShiftNamespace, check_security, read_config, env_config
from commands.openshift.api_obsolete_3 import do_login, do_logout
from commands.openshift.api import KubernetesConnection

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
def mock_default(ctx: ExtendedContext, namespace: str, mock_status: OpenShiftNamespace):
    ctx.forward(set_mock)


@mock.command('set')
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.argument('mock_status')
@click.pass_context
@check_security
def set_mock(ctx: ExtendedContext, namespace: str, mock_status: str):
    """Switch openshift mock status on environment"""
    env_vars = ctx.obj['config']['env_vars']
    config_env = env_config(ctx, namespace)
    valid_mock_statuses = [k.upper() for k in config_env['status'].keys()]
    mock_status = mock_status.upper()
    if mock_status not in valid_mock_statuses:
        ctx.chat.send_text((f"Invalid status `{mock_status}`. "
                            f"Mock status must be one of {', '.join(valid_mock_statuses)}"), is_error=True)
        return

    is_azure, prefix, project_name, result_text, should_exit = do_login(ctx, config_env, namespace)
    if should_exit:
        return

    statuses = config_env['status'][mock_status]
    vartemplates = config_env.get('vartemplate', {})
    if _check_recursive(ctx, vartemplates):
        return

    ctx.chat.send_text(f"Setting mock status to {mock_status} for project {project_name} on {namespace}...")

    for microservice_info, status in statuses.items():
        microservice, env_variable_value = _get_environment_values(env_vars, vartemplates, microservice_info, status)
        result_text += f"Setting {prefix + microservice} to {env_variable_value}...\n"
        environment_set_args = ['oc', 'set', 'env', '-n', project_name,  prefix + microservice, env_variable_value]
        environment_set_cmd = subprocess.run(environment_set_args, capture_output=True)
        if environment_set_cmd.returncode:
            result_text += environment_set_cmd.stderr.decode() + '\n\n'
        result_text += environment_set_cmd.stdout.decode() + '\n\n'

    result_text += do_logout(is_azure)
    # ctx.chat.send_text('```' + result_text + '```')

    ctx.chat.send_file(result_text.encode(), filename='mock.txt')


def _check_recursive(ctx, vartemplates):
    """Check that variables don't contain themselves"""
    for name, value in vartemplates.items():
        if '$' + name in value:
            ctx.chat.send_text(
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
def mock_check(ctx: ExtendedContext, namespace: str, excel: bool):
    """View current status of environment"""
    config_env = env_config(ctx, namespace)

    is_azure, prefix, project_name, result_text, should_exit = do_login(ctx, config_env, namespace)
    if should_exit:
        return

    first_status = list(config_env['status'].keys())[0]
    microservices = list(config_env['status'][first_status].keys())
    for microservice in microservices:
        environment_set_args = ['oc', 'set', 'env', '-n', project_name, prefix + microservice, '--list']
        env_var_list = subprocess.check_output(environment_set_args).decode()
        env_var_list = _masked_oc_password(env_var_list)
        result_text += env_var_list + '\n\n'

    result_text += do_logout(is_azure)

    ctx.chat.send_file(result_text.encode(), title='OpenShift Data', filename='openshift-data.txt')

@mock.command('view')
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.pass_context
@check_security
def mock_view(ctx: ExtendedContext, namespace: str, excel: bool):
    with KubernetesConnection(ctx, namespace) as k8s:
        deployments = k8s.apps_v1_api.list_namespaced_deployment(k8s.project_name)
    deployments_table = _make_deployments_table(deployments.items)
    ctx.chat.send_table(title='deployments', table=deployments_table, send_as_excel=excel)
