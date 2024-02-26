import json
import os
import re
import subprocess

from commands.extended_context import ExtendedContext


def azure_login(ctx: ExtendedContext, service_principal_id, service_principal_key, tenant_id, resource_group,
                cluster_name):
    az_cli = os.environ.get('AZ_CLI_EXECUTABLE', 'az')
    result_text = ""
    command_arguments = [
        az_cli, 'login',
        '--service-principal',
        '--username', service_principal_id,
        '--password', service_principal_key,
        '--tenant', tenant_id]
    ctx.logger.info(command_arguments)
    login_cmd = subprocess.run(command_arguments, capture_output=True)
    ctx.chat.send_text(f"Logging in to Azure...")
    login_result = json.loads(login_cmd.stdout)
    # ctx.chat.send_file(login_cmd.stdout, filename='login.json')
    ctx.chat.send_text(
        f"{login_result[0]['cloudName']} : {login_result[0]['name']} : {login_result[0]['user']['type']}")
    set_project_args = [
        az_cli, 'aks', 'get-credentials',
        '--overwrite-existing',
        '--name', cluster_name,
        '--resource-group', resource_group]
    ctx.logger.info(set_project_args)
    set_project_cmd = subprocess.run(set_project_args, capture_output=True)
    result_text += set_project_cmd.stdout.decode() + '\n' + set_project_cmd.stderr.decode() + '\n\n'
    convert_login_args = ['kubelogin', 'convert-kubeconfig', '-l', 'azurecli']
    convert_login_cmd = subprocess.run(convert_login_args, capture_output=True)
    result_text += convert_login_cmd.stdout.decode() + '\n' + convert_login_cmd.stderr.decode() + '\n\n'
    return result_text


def do_login(ctx: ExtendedContext, config_env, namespace):
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


def do_logout(is_azure):
    if not is_azure:
        logout_command = ['oc', 'logout']
        result_text = subprocess.check_output(logout_command).decode() + '\n\n'
        result_text = re.sub('\n{2,}', '\n', result_text)
    else:
        result_text = ""
    return result_text


def _get_project_name(env_config, environment):
    project_name = env_config.get('projectNameOverride', environment.lower())
    project_prefix = env_config.get('projectPrefix')
    if project_prefix:
        project_name = project_prefix + '-' + project_name
    return project_name
