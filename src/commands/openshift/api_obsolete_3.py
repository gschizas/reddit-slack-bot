import json
import os
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
