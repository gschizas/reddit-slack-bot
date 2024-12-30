import re
import requests

REDDIT_USERNAME_PATTERN = r'^<https://(?:www\.|old\.|new\.)?reddit\.com/u(?:ser)?/(?P<username>[a-zA-Z0-9_-]+)/?(?:\|\1)?>$'


def extract_username(username):
    if re.match(r'^\*.*\*$', username):
        username = username[1:-1]  # Remove slack formatting
    if re.match(r'^[a-zA-Z0-9_-]+$', username):
        pass  # Already a valid username
    elif m := re.match(REDDIT_USERNAME_PATTERN, username):
        username = m.group('username')  # Extract username from reddit link
    elif re.match(r'^u/[a-zA-Z0-9_-]+$', username):
        username = username.split('/')[-1]  # Extract username from reddit link
    else:
        username = None  # Invalid username
    return username


def extract_real_thread_id(thread_id):
    if thread_id.startswith('https://www.reddit.com/r/') and '/s/' in thread_id:
        response = requests.get(thread_id)
        thread_id = response.url.split('/')[6]
    elif '/' in thread_id:
        if thread_id.startswith('<') and thread_id.endswith('>'):  # slack link
            thread_id = thread_id[1:-1]
        if thread_id.startswith('http://') or thread_id.startswith('https://'):
            thread_id = thread_id.split('/')[6]
        elif thread_id.startswith('/'):
            thread_id = thread_id.split('/')[4]
        else:
            thread_id = thread_id.split('/')[3]
    return thread_id
