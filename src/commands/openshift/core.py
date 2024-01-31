import base64
import io
import subprocess
import tempfile
import threading
import time

import requests
from ruamel.yaml import YAML

from commands.extended_context import ExtendedContext
from commands.openshift.common import env_config

KUBERNETES_SERVICE_AAD_SERVER_GUID = '6dae42f8-4368-4678-94ff-3960e28e3630'
yaml = YAML()


class OpenShiftConnection:
    project_name: str
    server_url: str
    ses_k8s: requests.Session
    cert_authority = None

    def __init__(self, ctx: ExtendedContext, namespace: str):
        self.ctx = ctx
        self.namespace = namespace
        self.namespace_obj = env_config(self.ctx, self.namespace)
        self.server_url = self.namespace_obj['url']
        self.ses_main = requests.Session()
        self.is_azure = self.server_url == 'azure'

    def __enter__(self):
        if self.is_azure:
            self._login_azure()
        else:
            self._login_openshift(self.namespace)
        return self

    def _login_openshift(self, namespace):
        openshift_token = self.namespace_obj['credentials']
        self.ses_main.headers['Authorization'] = 'Bearer ' + openshift_token
        login_cmd = subprocess.run(
            ['oc', 'login', f'--token={openshift_token}', f'--server={self.server_url}'],
            capture_output=True)
        if login_cmd.returncode != 0:
            stderr_output = login_cmd.stderr.decode().strip()
            raise RuntimeError("Error while logging in", stderr_output)
        self.ses_k8s = self.ses_main
        self.project_name = namespace
        self.cert_authority = None

    def _login_azure(self):
        tenant_id = self.namespace_obj['credentials']['tenantId']
        service_principal_id = self.namespace_obj['credentials']['servicePrincipalId']
        service_principal_key = self.namespace_obj['credentials']['servicePrincipalKey']
        resource_group = self.namespace_obj['azure_resource_group']
        cluster_name = self.namespace_obj['azure_cluster_name']
        self.project_name = self.namespace_obj['project_name']
        login_page = self.ses_main.post(f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token', data={
            'client_id': service_principal_id,
            'grant_type': 'client_credentials',
            'client_info': 1,
            'client_secret': service_principal_key,
            'scope': 'https://management.core.windows.net/.default'
        })
        azure_token = login_page.json()['access_token']
        self.ses_main.headers['Authorization'] = 'Bearer ' + azure_token
        subscriptions_page = self.ses_main.get('https://management.azure.com/subscriptions?api-version=2019-11-01')
        subscription_id = subscriptions_page.json()['value'][0]['subscriptionId']
        aks_credentials_page = self.ses_main.post(
            (f'https://management.azure.com/subscriptions/{subscription_id}/resourceGroups'
             f'/{resource_group}/providers/Microsoft.ContainerService/managedClusters'
             f'/{cluster_name}/listClusterUserCredential?api-version=2022-03-01'))
        aks_credentials = aks_credentials_page.json()
        aks_value_raw = list(filter(lambda x: x['name'] == 'clusterUser', aks_credentials['kubeconfigs']))[0][
            'value']
        with io.BytesIO(base64.b64decode(aks_value_raw)) as f:
            aks_value = yaml.load(f)
        cluster_url = list(filter(lambda x: x['name'] == cluster_name, aks_value['clusters']))[0]['cluster'][
            'server']
        self.server_url = cluster_url + '/'
        self.cert_authority = tempfile.NamedTemporaryFile()
        cert_authority_data_raw = aks_value['clusters'][0]['cluster']['certificate-authority-data']
        cert_authority_data = base64.b64decode(cert_authority_data_raw)
        self.cert_authority.write(cert_authority_data)
        self.cert_authority.flush()
        kubernetes_token_raw = self.ses_main.post(
            f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token',
            data={
                'client_id': service_principal_id,
                'grant_type': 'client_credentials',
                'client_info': 1,
                'client_secret': service_principal_key,
                'scope': f'{KUBERNETES_SERVICE_AAD_SERVER_GUID}/.default'
            })
        kubernetes_token = kubernetes_token_raw.json()
        self.ses_k8s = requests.Session()
        self.ses_k8s.verify = self.cert_authority.name
        self.ses_k8s.headers['Authorization'] = 'Bearer ' + kubernetes_token['access_token']

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cert_authority:
            self.cert_authority.close()

    def get_pods(self, deployment: str):
        query = {'limit': 500}
        if deployment:
            query['labelSelector'] = f'deployment={deployment}'
        all_pods_raw = self.ses_k8s.get(
            f"{self.server_url}api/v1/namespaces/{self.project_name.lower()}/pods",
            params=query,
            verify=self.ses_k8s.verify)
        if not all_pods_raw.ok:
            self.ctx.chat.send_file(file_data=all_pods_raw.content, filename='error.txt')
            return []
        all_pods = all_pods_raw.json()
        return all_pods


class PortForwardProcess:
    proc: subprocess.Popen

    def __init__(self, ctx: ExtendedContext, pod_to_refresh: str):
        self.ctx = ctx
        self.pod_to_refresh = pod_to_refresh

    def __enter__(self):
        self.ctx.logger.debug(f"Starting port forward for {self.pod_to_refresh}")
        self.proc = subprocess.Popen(
            ['oc', 'port-forward', self.pod_to_refresh, '9999:8778'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            bufsize=0)
        out_line = []
        t = threading.Thread(target=_output_reader, args=(self.proc, out_line))
        t.start()
        time.sleep(1)
        t.join(timeout=5)
        while True:
            if self.proc.poll() is not None:
                if self.proc.returncode != 0:
                    self.proc.stderr.flush()
                    err_line = self.proc.stderr.readline()
                    self.ctx.logger.error(err_line.strip())
                break
            if (out_line == ['Forwarding from 127.0.0.1:9999 -> 8778'] or
                    out_line == ['Forwarding from 127.0.0.1:9999 -> 8778', 'Forwarding from [::1]:9999 -> 8778']):
                self.ctx.logger.debug("Port forward Listening ok")
                break
            time.sleep(0.2)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
            self.ctx.logger.info(f'== subprocess exited with rc = {self.proc.returncode}')
        except subprocess.TimeoutExpired:
            self.ctx.logger.error('subprocess did not terminate in time')


def _output_reader(proc, data):
    for line in iter(proc.stdout.readline, ''):
        data.append(line.strip())
