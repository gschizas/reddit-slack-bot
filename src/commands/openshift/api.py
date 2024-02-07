import requests

from commands.extended_context import ExtendedContext
from commands.openshift.common import env_config

_BOOL_TEXT = ['true', '1', 't', 'y', 'yes']


def _get_table(ses, url):
    def convert_type(rows_to_convert):
        for row in rows_to_convert:
            row_type = row[1]
            if row_type == 'boolean':
                yield row[0], str(row[2]).lower() in _BOOL_TEXT
            else:
                yield row[0], row[2]

    api_continue = ''
    result = []
    while True:
        rq = ses.get(url,
                     params={'limit': 500, 'continue': api_continue},
                     headers={'Accept': 'application/json;as=Table;v=v1beta1;g=meta.k8s.io, application/json'})
        if not rq.ok:
            rq.raise_for_status()
        col_names = [col['name'] for col in rq.json()['columnDefinitions']]
        col_types = [col['type'] for col in rq.json()['columnDefinitions']]
        rows = [dict(convert_type(zip(col_names, col_types, row['cells']))) for row in rq.json()['rows']]
        result.extend(rows)
        if 'continue' in rq.json()['metadata']:
            api_continue = rq.json()['metadata']['continue']
        else:
            break
    return result


def _openshift_session(ctx: ExtendedContext, namespace: str, enforce_content_type: bool = True):
    config: dict = env_config(ctx, namespace)
    openshift_token = config['credentials']
    server_url = config['url']
    ses = requests.session()
    ses.headers['Authorization'] = 'Bearer ' + openshift_token
    ses.headers['Accept'] = 'application/json, */*'
    if enforce_content_type:
        ses.headers['Content-Type'] = 'application/strategic-merge-patch+json'
    return server_url, ses


def get_deployments(ctx: ExtendedContext, namespace: str):
    server_url, ses = _openshift_session(ctx, namespace, False)
    return _get_table(ses, f'{server_url}apis/apps/v1/namespaces/{namespace}/deployments')


def change_deployment_pause_state(ctx: ExtendedContext, namespace: str, deployment_name: str, pause_state: bool):
    server_url, ses = _openshift_session(ctx, namespace)
    rq = ses.patch(
        f'{server_url}apis/apps/v1/namespaces/{namespace}/deployments/{deployment_name}',
        json={"spec": {"paused": pause_state}})
    return rq.json()


def get_cronjobs(ctx: ExtendedContext, namespace: str):
    server_url, ses = _openshift_session(ctx, namespace, False)
    return _get_table(ses, f'{server_url}apis/batch/v1/namespaces/{namespace}/cronjobs')


def change_cronjob_suspend_state(ctx: ExtendedContext, namespace: str, cronjob_name: str, suspend_state: bool):
    server_url, ses = _openshift_session(ctx, namespace)
    rq = ses.patch(
        f'{server_url}apis/batch/v1/namespaces/{namespace}/cronjobs/{cronjob_name}',
        json={"spec": {"suspend": suspend_state}})
    return rq.json()
