import re


def extract_username(username):
    if re.match('^[a-zA-Z0-9_-]+$', username):
        pass
    elif m := re.match(r'^<https://www.reddit.com/user/(?P<username>[a-zA-Z0-9_-]+)(?:\|\1)?>$', username):
        username = m.group('username')
    elif re.match(r'^u/[a-zA-Z0-9_-]+$', username):
        username = username.split('/')[-1]
    else:
        username = None
    return username


def extract_real_thread_id(thread_id):
    if '/' in thread_id:
        if thread_id.startswith('<') and thread_id.endswith('>'):  # slack link
            thread_id = thread_id[1:-1]
        if thread_id.startswith('http://') or thread_id.startswith('https://'):
            thread_id = thread_id.split('/')[6]
        elif thread_id.startswith('/'):
            thread_id = thread_id.split('/')[4]
        else:
            thread_id = thread_id.split('/')[3]
    return thread_id