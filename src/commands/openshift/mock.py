import os
import re
import subprocess
from string import Template

import click
from ruamel.yaml import YAML

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext
from commands.openshift.common import OpenShiftNamespace, azure_login, check_security, read_config, env_config

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
    ctx.obj['security_text'] = {
        'set': 'switch mock status',
        'check': 'view mock status',
        'setapi': 'switch mock status via api'}


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

    is_azure, prefix, project_name, result_text, should_exit = _do_login(ctx, config_env, namespace)
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
        environment_set_args = ['oc', 'set', 'env', '-n', project_name, prefix + microservice, env_variable_value]
        environment_set_cmd = subprocess.run(environment_set_args, capture_output=True)
        if environment_set_cmd.returncode:
            result_text += environment_set_cmd.stderr.decode() + '\n\n'
        result_text += environment_set_cmd.stdout.decode() + '\n\n'
        break

    result_text += _do_logout(is_azure)
    # ctx.chat.send_text('```' + result_text + '```')

    ctx.chat.send_file(result_text.encode(), filename='mock.txt')


@mock.command('setapi')
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.argument('mock_status')
@click.pass_context
@check_security
def set_api_mock(ctx: ExtendedContext, namespace: str, mock_status: str):
    """Switch openshift mock status on environment"""
    env_vars = ctx.obj['config']['env_vars']
    config_env = env_config(ctx, namespace)
    valid_mock_statuses = [k.upper() for k in config_env['status'].keys()]
    mock_status = mock_status.upper()
    if mock_status not in valid_mock_statuses:
        ctx.chat.send_text((f"Invalid status `{mock_status}`. "
                            f"Mock status must be one of {', '.join(valid_mock_statuses)}"), is_error=True)
        return

    is_azure, should_exit, prefix, project_name, core_client, apps_client = _do_login_api(ctx, config_env, namespace)

    if '/' in prefix: prefix = prefix.split('/')[-1]

    if should_exit:
        return

    statuses = config_env['status'][mock_status]
    vartemplates = config_env.get('vartemplate', {})
    if _check_recursive(ctx, vartemplates):
        return

    ctx.chat.send_text(f"Setting mock status to {mock_status} for project {project_name} on {namespace}...")

    result_table = []

    for microservice_info, status in statuses.items():
        microservice, env_variable_value = _get_environment_values(env_vars, vartemplates, microservice_info, status)
        patch_body = {"spec": {"template": {"spec": {
            "$setElementOrder/containers": [{"name": prefix + microservice}],
            "containers": [{"env": [], "name": prefix + microservice}]}}}}
        if env_variable_value:
            patch_body['spec']['template']['spec']['containers'][0]['env'].append(
                {"name": "SPRING_PROFILES_ACTIVE", "value": env_variable_value})
        else:
            patch_body['spec']['template']['spec']['containers'][0]['env'].append(
                {"name": "SPRING_PROFILES_ACTIVE", "$patch": "delete"})
        patch_cmd = apps_client.patch_namespaced_deployment(prefix + microservice, project_name, patch_body)
        found_container = \
            [container for container in patch_cmd.spec.template.spec.containers if
             container.name == prefix + microservice][0]
        env_value = [envvar for envvar in found_container.env if envvar.name == 'SPRING_PROFILES_ACTIVE'][0].value

        result_table.append({
            'microservice': microservice,
            'value': env_value,
            'prefixed microservice': prefix + microservice,
            'environment variable value': env_variable_value,
            'environment variable value is None': env_variable_value is None})
        break

    ctx.chat.send_table(table=result_table, title="Change Mock Configuration")


def _do_login(ctx: ExtendedContext, config_env, namespace):
    result_text = ""
    site = config_env['site']
    prefix = config_env['prefix']
    project_name = _get_project_name(config_env, namespace)
    is_azure = site == 'azure'
    should_exit = False
    if is_azure:
        result_text += azure_login(
            ctx,
            config_env['credentials']['servicePrincipalId'],
            config_env['credentials']['servicePrincipalKey'],
            config_env['credentials']['tenantId'],
            config_env['azure_resource_group'],
            config_env['azure_cluster_name'])
    else:
        oc_token = config_env['credentials']
        login_cmd = subprocess.run(['oc', 'login', site, f'--token={oc_token}'], capture_output=True)
        login_result = login_cmd.stderr.decode().strip()
        if login_cmd.returncode != 0:
            ctx.chat.send_text(f"Error while logging in:\n```{login_result}```", is_error=True)
            should_exit = True
    return is_azure, prefix, project_name, result_text, should_exit


def _do_login_api(ctx: ExtendedContext, config_env, namespace: str):
    import kubernetes.config
    site = config_env['site']
    prefix = config_env['prefix']
    project_name = _get_project_name(config_env, namespace)
    is_azure = site == 'azure'
    if is_azure:
        import urllib3
        urllib3.disable_warnings()
        return True, True, None, None, None, None
    else:
        openshift_token = config_env['credentials']
        configuration = kubernetes.client.Configuration()
        if 'REQUESTS_CA_BUNDLE' in os.environ:
            configuration.ssl_ca_cert = os.environ['REQUESTS_CA_BUNDLE']
        configuration.proxy = 'http://localhost:8855'
        if site.endswith('/'): site = site[:-1]
        configuration.host = site
        configuration.api_key = {"authorization": "Bearer " + openshift_token}
        api_client = kubernetes.client.ApiClient(configuration)
        core_client = kubernetes.client.CoreV1Api(api_client)
        apps_client = kubernetes.client.AppsV1Api(api_client)
    return is_azure, False, prefix, project_name, core_client, apps_client


def _do_logout(is_azure):
    if not is_azure:
        logout_command = ['oc', 'logout']
        result_text = subprocess.check_output(logout_command).decode() + '\n\n'
        result_text = re.sub('\n{2,}', '\n', result_text)
    else:
        result_text = ""
    return result_text


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


@mock.command('check')  # , aliases=['get', 'view']
@click.argument('namespace', type=OpenShiftNamespace(_mock_config(), force_upper=True))
@click.option('-x', '--excel', is_flag=True, default=False)
@click.pass_context
@check_security
def mock_check(ctx: ExtendedContext, namespace: str, excel: bool):
    """View current status of environment"""
    config_env = env_config(ctx, namespace)
    is_azure, should_exit, prefix, project_name, core_client, apps_client = _do_login_api(ctx, config_env, namespace)

    if '/' in prefix: prefix = prefix.split('/')[-1]

    if should_exit:
        return

    first_status = list(config_env['status'].keys())[0]
    microservices = list(config_env['status'][first_status].keys())
    result = []
    for microservice in microservices:
        deployment_data = apps_client.read_namespaced_deployment(prefix + microservice, project_name)
        found_container = \
            [container for container in deployment_data.spec.template.spec.containers if
             container.name == prefix + microservice][0]
        env_value = [envvar for envvar in found_container.env if envvar.name == 'SPRING_PROFILES_ACTIVE'][0].value
        result.append({'microservice': microservice, 'value': env_value})

    ctx.chat.send_table(title="Microservice Status", table=result, send_as_excel=excel)
