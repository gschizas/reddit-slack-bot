import requests


def get_deployments(config, namespace):
    openshift_token = config['openshift_token']
    server_url = config['url']

    ses = requests.session()
    ses.headers['Authorization'] = 'Bearer ' + openshift_token
    deployments = []
    api_continue = ''
    while True:
        rq = ses.get(f'{server_url}apis/apps/v1/namespaces/{namespace}/deployments',
                     params={'limit': 500, 'continue': api_continue},
                     headers={'Accept': 'application/json;as=Table;v=v1beta1;g=meta.k8s.io, application/json'})
        col_defs = [col['name'] for col in rq.json()['columnDefinitions']]
        rows = [dict(zip(col_defs, row['cells'])) for row in rq.json()['rows']]
        deployments.extend(rows)
        if 'continue' in rq.json()['metadata']:
            api_continue = rq.json()['metadata']['continue']
        else:
            break
    return deployments


def change_pause_state(config, namespace, deployment_name, pause_state):
    openshift_token = config['openshift_token']
    server_url = config['url']
    ses = requests.session()
    ses.headers['Authorization'] = 'Bearer ' + openshift_token
    ses.headers['Accept'] = 'application/json, */*'
    ses.headers['Content-Type'] = 'application/strategic-merge-patch+json'
    rq = ses.patch(
        f'{server_url}apis/apps/v1/namespaces/{namespace}/deployments/{deployment_name}',
        json={"spec": {"paused": pause_state}})
    return rq.json()
