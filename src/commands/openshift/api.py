import base64
import io
import pathlib

import requests
import urllib3
import kubernetes.client
import kubernetes.stream
from ruamel.yaml import YAML

from commands.extended_context import ExtendedContext


class KubernetesConnection:
    KUBERNETES_SERVICE_AAD_SERVER_GUID = '6dae42f8-4368-4678-94ff-3960e28e3630'
    config: dict
    project_name: str
    server_url: str
    cert_authority: str
    api_key: str

    def __init__(self, ctx: ExtendedContext, namespace: str):
        self.ctx = ctx
        self.namespace = namespace
        self.project_name = self.namespace
        self.config = self.ctx.obj['config']['environments'][self.namespace]
        self.server_url = self.config['url']
        self.is_azure = self.server_url == 'azure'

    def _login_openshift(self):
        self.api_key = self.config['credentials']

    def _login_azure(self):
        creds = self.config['credentials']
        self.project_name = self.config['project_name']
        yaml = YAML()
        session = requests.Session()
        login_page = session.post(
            f'https://login.microsoftonline.com/{creds["tenantId"]}/oauth2/v2.0/token',
            data={
                'client_id': (creds['servicePrincipalId']),
                'grant_type': 'client_credentials',
                'client_info': 1,
                'client_secret': (creds['servicePrincipalKey']),
                'scope': 'https://management.core.windows.net/.default'
            })
        azure_token = login_page.json()['access_token']
        session.headers['Authorization'] = 'Bearer ' + azure_token
        subscriptions_page = session.get('https://management.azure.com/subscriptions?api-version=2019-11-01')
        subscription_id = subscriptions_page.json()['value'][0]['subscriptionId']
        aks_credentials_page = session.post(
            (f'https://management.azure.com/subscriptions/{subscription_id}/resourceGroups'
             f'/{self.config["azure_resource_group"]}/providers/Microsoft.ContainerService/managedClusters'
             f'/{self.config["azure_cluster_name"]}/listClusterUserCredential?api-version=2022-03-01'))
        aks_credentials = aks_credentials_page.json()
        aks_value_raw = list(filter(lambda x: x['name'] == 'clusterUser', aks_credentials['kubeconfigs']))[0]['value']
        with io.BytesIO(base64.b64decode(aks_value_raw)) as f:
            aks_value = yaml.load(f)
        cluster_url = \
            list(filter(lambda x: x['name'] == self.config['azure_cluster_name'], aks_value['clusters']))[0]['cluster'][
                'server']
        self.server_url = cluster_url + '/'

        #
        # self.cert_authority = tempfile.NamedTemporaryFile()
        # cert_authority_data_raw = aks_value['clusters'][0]['cluster']['certificate-authority-data']
        # cert_authority_data = base64.b64decode(cert_authority_data_raw)
        # self.cert_authority.write(cert_authority_data)
        # self.cert_authority.flush()

        kubernetes_token_raw = session.post(
            f'https://login.microsoftonline.com/{creds["tenantId"]}/oauth2/v2.0/token',
            data={
                'client_id': (creds['servicePrincipalId']),
                'grant_type': 'client_credentials',
                'client_info': 1,
                'client_secret': (creds['servicePrincipalKey']),
                'scope': f'{KubernetesConnection.KUBERNETES_SERVICE_AAD_SERVER_GUID}/.default'
            })
        kubernetes_token = kubernetes_token_raw.json()
        self.api_key = kubernetes_token['access_token']

    def __enter__(self):
        if 'cert' in self.config:
            self.cert_authority = str((pathlib.Path('data') / self.config['cert']).resolve())

        if self.is_azure:
            self._login_azure()
        else:
            self._login_openshift()

        if self.server_url.endswith('/'): self.server_url = self.server_url[:-1]

        kubernetes_configuration = kubernetes.client.Configuration()
        kubernetes_configuration.api_key_prefix['authorization'] = 'Bearer'
        kubernetes_configuration.api_key['authorization'] = self.api_key
        kubernetes_configuration.host = self.server_url

        if self.cert_authority:
            kubernetes_configuration.ssl_ca_cert = self.cert_authority
            # kubernetes_configuration.host = self.cert_authority.name

        self.api_client = kubernetes.client.ApiClient(kubernetes_configuration)
        self.core_v1_api = kubernetes.client.CoreV1Api(self.api_client)
        self.well_known_api = kubernetes.client.WellKnownApi(self.api_client)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.api_client:
            self.api_client.close()
        # if self.cert_authority:
        #     self.cert_authority.close()

    def exec_portforward_command(self, namespace, pod_name, command_name):
        original_create_connection = urllib3.util.connection.create_connection

        def kubernetes_create_connection(address, *args, **kwargs):
            dns_name = address[0]
            if isinstance(dns_name, bytes):
                dns_name = dns_name.decode()
            dns_name = dns_name.split(".")
            if dns_name[-1] != 'kubernetes':
                return original_create_connection(address, *args, **kwargs)
            if len(dns_name) not in (3, 4):
                raise RuntimeError("Unexpected kubernetes DNS name.")
            namespace = dns_name[-2]
            name = dns_name[0]
            port = address[1]
            if len(dns_name) == 4:
                if dns_name[1] != 'pod':
                    raise RuntimeError(
                        f"Unsupported resource type: {dns_name[1]}")
            pf = kubernetes.stream.portforward(self.core_v1_api, name, namespace, ports=str(port))
            return pf.socket(port)

        urllib3.util.connection.create_connection = kubernetes_create_connection

        response = requests.get(f'http://{pod_name}.pod.{namespace}.kubernetes:8778/{command_name}',
                                proxies={'http': None, 'https': None})
        urllib3.util.connection.create_connection = original_create_connection
        return response.json()
