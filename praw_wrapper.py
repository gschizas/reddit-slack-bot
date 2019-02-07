import datetime
import os
import uuid
from urllib.parse import urlparse, parse_qs

import praw

DEFAULT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
DEFAULT_CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET')


def praw_wrapper(config=None, user_agent=None, client_id=None, client_secret=None, redirect_url=None, scopes=None):
    if config:
        user_agent = config['main'].get('user_agent')
        client_id = config['main'].get('client_id')
        client_secret = config['main'].get('client_secret')
        redirect_url = config['main'].get('redirect_url')
        scopes = config['main'].get('scopes')

    if not user_agent:
        user_agent = 'python:gr.terrasoft.reddit.scratch:v' + datetime.date.today().isoformat() + ' (by /u/gschizas)'
    if not client_id:
        client_id = DEFAULT_CLIENT_ID
    if not client_secret:
        client_secret = DEFAULT_CLIENT_SECRET
    if not redirect_url:
        redirect_url = 'https://example.com/authorize_callback'
    if not scopes:
        scopes = ['*']

    user_agent_key = user_agent.split(':')[1]

    if not config:
        if os.path.exists(user_agent_key + '.refresh_token'):
            with open(user_agent_key + '.refresh_token', 'r') as f:
                refresh_token = f.read()
        else:
            refresh_token = None
    else:
        refresh_token = config['main'].get('refresh_token')

    if refresh_token:
        praw_instance = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            user_agent=user_agent)
    else:
        praw_instance = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_url,
            user_agent=user_agent)
        state = uuid.uuid4().hex
        print('Visit the following URL:', praw_instance.auth.url(scopes, state))
        url = input('Result URL: ')
        query = parse_qs(urlparse(url).query)
        assert state == query['state'][0]
        code = query['code'][0]
        refresh_token = praw_instance.auth.authorize(code)
        if config:
            config['main']['refresh_token'] = refresh_token
        else:
            with open(user_agent_key + '.refresh_token', 'w') as f:
                f.write(refresh_token)
    return praw_instance
