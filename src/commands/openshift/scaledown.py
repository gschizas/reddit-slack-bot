import subprocess
import shlex

import click
import requests
from commands.openshift.common import read_config, user_allowed, OpenShiftNamespace
from ruamel.yaml import YAML

from commands import gyrobot, chat, logger

yaml = YAML()
all_users = []
all_users_last_update = 0


def _scaledown_config():
    env_var = 'OPENSHIFT_SCALEDOWN'
    return read_config(env_var)


@gyrobot.command('scaledown')
@click.argument('namespace', type=OpenShiftNamespace(_scaledown_config()))
@click.pass_context
def scaledown(ctx, namespace):
    namespace_obj = _scaledown_config()[namespace]
    server_url = namespace_obj['url']
    allowed_users = namespace_obj['users']
    if not user_allowed(chat(ctx).user_id, allowed_users):
        chat(ctx).send_text(f"You don't have permission to scale down kubernetes objects.", is_error=True)
        return
    allowed_channels = namespace_obj['channels']
    channel_name = chat(ctx).channel_name
    if channel_name not in allowed_channels:
        chat(ctx).send_text(f"Kubernetes scale down commands are not allowed in {channel_name}", is_error=True)
        return
    openshift_token = namespace_obj['credentials']

    result = ""

    login_cmd = subprocess.run(['oc', 'login', f'--token={openshift_token}', f'--server={server_url}'], capture_output=True)
    if login_cmd.returncode != 0:
        chat(ctx).send_text("Error while logging in:\n```" + login_cmd.stderr.decode().strip() + "```", is_error=True)
        return

    whoami_cmd = subprocess.run(['oc', 'whoami'], capture_output=True)
    result += whoami_cmd.stdout.decode() + '\n'

    change_project_cmd = subprocess.run(['oc', 'project', namespace], capture_output=True)
    if change_project_cmd.returncode != 0:
        chat(ctx).send_text(f"Error while selecting project {namespace} in:\n```" + change_project_cmd.stderr.decode().strip() + "```", is_error=True)
        return

    project_cmd = subprocess.run(['oc', 'project'], capture_output=True)
    result += project_cmd.stdout.decode() + '\n'

    deployments_to_scaledown_cmd_line = ['oc', 'get', '-o', 'go-template={{range .items}}{{.metadata.name}}{{"\\n"}}{{end}}', 'deployment']
    deployments_to_scaledown_cmd = subprocess.run(deployments_to_scaledown_cmd_line, capture_output=True)
    if deployments_to_scaledown_cmd.returncode != 0:
        chat(ctx).send_text(f"Error while retrieveing deployments:\n```" + deployments_to_scaledown_cmd.stderr.decode().strip() + "```", is_error=True)
        return

    deployments_to_scaledown_raw = deployments_to_scaledown_cmd.stdout.decode()
    deployments_to_scaledown = deployments_to_scaledown_raw.strip().splitlines()
    if len(deployments_to_scaledown) == 0:
        chat(ctx).send_text(f"Couldn't find any deployments on {namespace} to scale down", is_error=True)
        return

    for deployment_to_scaledown in deployments_to_scaledown:
        if deployment_to_scaledown in namespace_obj.get('~deployments', []): continue # ignore deployment
        result += "\n"
        scaledown_cmd_line = ['oc', 'scale', 'deployment', deployment_to_scaledown, '--replicas=0']
        result += shlex.join(scaledown_cmd_line)
        scaledown_cmd = subprocess.run(scaledown_cmd_line, capture_output=True)
        if scaledown_cmd.returncode != 0:
            result += f"\nError {scaledown_cmd.returncode} while scaling down deployment {deployment_to_scaledown} to scale down\n"
        result += scaledown_cmd.stdout.decode().strip() + "\n"
        result += scaledown_cmd.stderr.decode().strip() + "\n"

    for resource_to_scaledown in namespace_obj['resources']:
        result += "\n"
        scaledown_cmd_line = ['oc', 'scale', 'sts', resource_to_scaledown, '--replicas=0']
        scaledown_cmd = subprocess.run(scaledown_cmd_line, capture_output=True)
        if scaledown_cmd.returncode != 0:
            result += f"\nError {scaledown_cmd.returncode} while scaling down stateful set {resource_to_scaledown} to scale down\n"
        result += scaledown_cmd.stdout.decode().strip() + "\n"
        result += scaledown_cmd.stderr.decode().strip() + "\n"

    result_cmd = subprocess.run(['oc', 'get', 'pod'], capture_output=True)
    if result_cmd.returncode != 0:
        chat(ctx).send_text(f"Error while getting pod status", is_error=True)
    result += result_cmd.stdout.decode().strip() + "\n"
    result += result_cmd.stderr.decode().strip() + "\n"


    logout_cmd = subprocess.run(['oc', 'logout', f'--server={server_url}'], capture_output=True)
    result += logout_cmd.stdout.decode().strip() + "\n"
    result += logout_cmd.stderr.decode().strip() + "\n"

    chat(ctx).send_file(file_data = result.encode(), filename='scaledown.txt')
