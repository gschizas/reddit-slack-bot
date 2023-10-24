import base64
import collections
import datetime
import json
import os
import pathlib
import re
import urllib
import unicodedata
import zlib

import click
import praw
import requests
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict

from bot_framework.yaml_wrapper import yaml
from commands import gyrobot, chat, subreddit, DefaultCommandGroup, reddit_session, logger, ClickAliasedGroup
from commands.reddit.common import extract_username, extract_real_thread_id
from state_file import state_file

ARCHIVE_URL = 'http://archive.is'
CHROME_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/77.0.3865.90 Safari/537.36')

_archive_session = requests.Session()
_archive_session.mount(ARCHIVE_URL, HTTPAdapter(max_retries=5))


def _send_usernote(ctx, redditor_username, notes, warnings, usernote_colors, mod_names, verbose):
    text = f'Usernotes for user {redditor_username}'
    fields = []
    for note in notes['ns']:
        warning = warnings[note['w']] or ''
        when = datetime.datetime.fromtimestamp(note['t'])
        note_text = note['n']
        color = usernote_colors.get(warning, {'color': '#000000'})['color']
        warning_text = usernote_colors.get(warning, {'text': '?' + warning})['text']
        link_parts = note['l'].split(',')
        link_href = '???'
        if link_parts[0] == 'l':
            if len(link_parts) == 2:
                link_href = f'{reddit_session(ctx).config.reddit_url}/r/{subreddit(ctx).display_name}/comments/{link_parts[1]}'
            elif len(link_parts) == 3:
                link_href = (
                    f'{reddit_session(ctx).config.reddit_url}/r/{subreddit(ctx).display_name}/comments/'
                    f'{link_parts[1]}/-/{link_parts[2]}')
        else:
            link_href = note['l']
        mod_name = mod_names[note['m']]
        if verbose == 'short':
            fields.append({
                'color': color,
                'text': f"<!date^{int(when.timestamp())}^{{date_short}}|{when.isoformat()}>: {note_text}\n"
            })
        elif verbose == 'long':
            fields.append({
                'color': color,
                'text': (f"{warning_text} at <!date^{int(when.timestamp())}"
                         f"^{{date_short}} {{time}}|{when.isoformat()}>:"
                         f"`{note_text}` for <{link_href}> by {mod_name}\n")
            })
        else:
            fields.append({
                'color': color,
                'text': (
                    f"{warning_text} at <!date^{int(when.timestamp())}^{{date_short}} {{time}}|"
                    f"{when.isoformat()}>: `{note_text}`\n")
            })
    chat(ctx).send_fields(text, fields)


@gyrobot.group('modqueue', cls=DefaultCommandGroup)
def modqueue():
    pass


@modqueue.command('posts')
@click.pass_context
def modqueue_posts(ctx):
    """Display posts from the modqueue"""
    text = ''
    for s in subreddit(ctx).mod.modqueue(only='submissions'):
        text += s.title + '\n' + s.url + '\n'
    else:
        text = "No posts in modqueue"
    chat(ctx).send_text(text)


@modqueue.command('comments')
@click.pass_context
def modqueue_comments(ctx):
    """Display comments from the modqueue"""
    text = ''
    for c in subreddit(ctx).mod.modqueue(only='comments', limit=10):
        text += reddit_session(ctx).config.reddit_url + c.permalink + '\n```\n' + c.body[:80] + '\n```\n'
    else:
        text = "No comments in modqueue"
    chat(ctx).send_text(text)


@modqueue.command('grouped')
@click.pass_context
def modqueue_grouped(ctx):
    modqueue_list = list(subreddit(ctx).mod.modqueue(limit=None))
    if len(modqueue_list) < 1:
        chat(ctx).send_text('Modqueue is empty!', is_error=True)
        return
    grouped_step_1 = collections.Counter([mq.author for mq in modqueue_list])
    grouped_step_2 = sorted(grouped_step_1.items(), key=lambda x: -x[1])
    grouped_step_3 = [item for item in grouped_step_2 if item[1] > 1]
    grouped_items = [f"{item[1]} items from <{reddit_session(ctx).config.reddit_url}/u/{item[0].name}|{item[0].name}>"
                     for item in grouped_step_3]
    if len(grouped_items) < 1:
        chat(ctx).send_text('No duplicate entries in modqueue!', is_error=True)
        return
    inner_text = ''
    blocks = []
    for item in grouped_items:
        if len(inner_text) < 2000:
            inner_text += item + '\n'
        else:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": inner_text.strip('\n')}})
            inner_text = ''
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": inner_text}})
    chat(ctx).send_blocks(blocks)


@modqueue.command('length', default_command=True)
@click.pass_context
def modqueue_length(ctx):
    """Show modqueue length"""
    posts_modqueue_length = len(list(subreddit(ctx).mod.modqueue(only='submissions', limit=None)))
    comments_modqueue_length = len(list(subreddit(ctx).mod.modqueue(only='comments', limit=None)))
    modmail_open_length = len(list(subreddit(ctx).modmail.conversations(limit=1000)))
    post_descr = 'posts' if posts_modqueue_length != 1 else 'post'
    comment_descr = 'comments' if comments_modqueue_length != 1 else 'comment'
    modmail_descr = 'modmails' if modmail_open_length != 1 else 'modmail'
    if posts_modqueue_length == 0 and comments_modqueue_length == 0:
        with state_file('kitteh') as pref_cache:
            default_creature = ("The queue is clean! Kitteh is pleased. "
                                "https://www.redditstatic.com/desktop2x/img/snoomoji/cat_blep.png")
            default_team_creature = pref_cache.get('default', default_creature)
            creature = pref_cache.get(chat(ctx).user_id, default_team_creature)
        if modmail_open_length > 0:
            creature += f"\nBut {modmail_open_length} {modmail_descr} remain"
        chat(ctx).send_text(creature)
    else:
        reddit_url = reddit_session(ctx).config.reddit_url
        subreddit_name = subreddit(ctx).display_name
        modqueue_comments_url = f"{reddit_url}/r/{subreddit_name}/about/modqueue?only=comments"
        modqueue_posts_url = f"{reddit_url}/r/{subreddit_name}/about/modqueue?only=links"

        text = (f"Modqueue contains <{modqueue_posts_url}|{posts_modqueue_length} {post_descr}>, "
                f"<{modqueue_comments_url}|{comments_modqueue_length} {comment_descr}> and "
                f"{modmail_open_length} {modmail_descr}")
        chat(ctx).send_text(text)


# do_mq = do_modqueue_length
# do_modqueue = do_modqueue_length


@gyrobot.command('usernotes')
@click.argument('user')
@click.argument('verbose', required=False)
@click.pass_context
def usernotes(ctx, user, verbose=None):
    """Display usernotes of a user"""
    redditor_username = user
    if (redditor_username := extract_username(redditor_username)) is None:
        chat(ctx).send_text(f'{redditor_username} is not a valid username', is_error=True)
        return
    verbose = verbose or ''
    if verbose.lower() not in ('short', 'long'):
        verbose = ''
    tb_notes = subreddit(ctx).wiki['usernotes']
    tb_notes_1 = json.loads(tb_notes.content_md)
    warnings = tb_notes_1['constants']['warnings']
    tb_notes_2 = CaseInsensitiveDict(json.loads(zlib.decompress(base64.b64decode(tb_notes_1['blob'])).decode()))
    tb_config = json.loads(subreddit(ctx).wiki['toolbox'].content_md)
    usernote_colors = {c['key']: c for c in tb_config['usernoteColors']}
    notes = tb_notes_2.get(redditor_username.lower())
    if notes is None:
        chat(ctx).send_text(f"user {redditor_username} doesn't have any user notes")
        return

    mod_names = tb_notes_1['constants']['users']

    _send_usernote(ctx, redditor_username, notes, warnings, usernote_colors, mod_names, verbose)


@gyrobot.command('youtube_post_info')
@click.argument('url')
@click.pass_context
def youtube_post_info(ctx, url):
    """Get YouTube media URL"""
    thread_id = extract_real_thread_id(url)
    post = reddit_session(ctx).submission(thread_id)
    post._fetch()
    media = getattr(post, 'media', None)
    if not media:
        chat(ctx).send_text('Not a YouTube post', is_error=True)
        return
    try:
        author_url = media['oembed']['author_url']
        chat(ctx).send_text(f"Author URL: {author_url}")
    except Exception as e:
        chat(ctx).send_text(repr(e), is_error=True)


@gyrobot.command('add_domain_tag')
@click.argument('url')
@click.argument('color')
@click.pass_context
def add_domain_tag(ctx, url, color):
    """Add a tag to a domain"""
    toolbox_data = json.loads(subreddit(ctx).wiki['toolbox'].content_md)
    if re.match('<.*>', url):
        url = url[1:-1]
    url_obj = urllib.parse.urlparse(url)
    final_url = url_obj.netloc
    if len(url_obj.path) > 1:
        final_url += url_obj.path
    if not re.match(r'\#[0-9a-f]{6}', color, re.IGNORECASE):
        chat(ctx).send_text(f"{color} is not a good color on you!")
        return
    entry = [tag for tag in toolbox_data['domainTags'] if tag['name'] == final_url]
    if entry:
        entry['color'] = color
    else:
        toolbox_data['domainTags'].append({'name': final_url, 'color': color})
    subreddit(ctx).wiki['toolbox'].edit(json.dumps(toolbox_data), 'Updated by slack')
    chat(ctx).send_text(f"Added color {color} for domain {final_url}")


@gyrobot.command('add_policy')
@click.argument('title')
@click.pass_context
def add_policy(ctx, title):
    """Add a minor policy change done via Slack's #modpolicy channel"""
    permalink_response = chat(ctx).web_client.chat_getPermalink(
        channel=chat(ctx).channel_id,
        message_ts=chat(ctx).message['ts'])
    permalink = permalink_response['permalink']
    policy_subreddit = os.environ.get('REDDIT_POLICY_SUBREDDIT', subreddit(ctx).display_name)
    policy_page = os.environ.get('REDDIT_POLICY_PAGE', 'mod_policy_votes')
    sr = reddit_session(ctx).subreddit(policy_subreddit)
    existing_page = sr.wiki[policy_page]
    content = existing_page.content_md
    today_text = datetime.datetime.strftime(datetime.datetime.utcnow(), '%d/%m/%Y')
    title = re.sub(r'\s', ' ', title)
    title = title.replace('|', '\xa6')
    new_content = f'\r\n{today_text}|{title}|[Slack]({permalink})'
    content = content.strip() + new_content
    existing_page.edit(content)
    chat(ctx).send_text(f"Policy recorded: `{new_content.strip()}`")


def _archive_page(url):
    url = url.replace('//www.reddit.com/', '//old.reddit.com/')

    # start_page = requests.get(ARCHIVE_URL)
    # soup = BeautifulSoup(start_page.text, 'lxml')
    # main_form = soup.find('form', {'id': 'submiturl'})
    # submit_id = main_form.find('input', {'name': 'submitid'})['value']
    p2 = _archive_session.post(
        f'{ARCHIVE_URL}/submit/',
        data={
            'url': url
        },
        headers={
            'Referer': 'http://archive.is',
            'User-Agent': CHROME_USER_AGENT})
    if p2.url == f'{ARCHIVE_URL}/submit/':
        return p2.headers['Refresh'][6:]
    else:
        return p2.url


@gyrobot.command('archive')
@click.argument('username')
@click.pass_context
def archive_user(ctx, username):
    """\
    Archive all posts and comments of a user. This helps preserving the
    account history when nuking the user's contribution (especially when
    the user then deletes their account).
    Only one argument, the username"""
    if (username := extract_username(username)) is None:
        chat(ctx).send_text(f'{username} is not a valid username', is_error=True)
        return
    user = reddit_session(ctx).redditor(username)

    urls_to_archive = []
    urls_to_archive.append(f'{reddit_session(ctx).config.reddit_url}/user/{user.name}/submitted/')

    submissions = list(user.submissions.new(limit=None))
    for s in submissions:
        urls_to_archive.append(reddit_session(ctx).config.reddit_url + s.permalink)

    comments = list(user.comments.new(limit=None))
    url_base = f'{reddit_session(ctx).config.reddit_url}/user/{user.name}/comments?sort=new'
    urls_to_archive.append(url_base)
    for c in comments[24::25]:
        after = c.name
        url = url_base + '&count=25&after=' + after
        urls_to_archive.append(url)
    chat(ctx).send_file(
        file_data='\n'.join(urls_to_archive).encode(),
        filename=f'archive-{user}-request.txt')
    final_urls = [_archive_page(url) for url in urls_to_archive]
    chat(ctx).send_file(
        file_data='\n'.join(final_urls).encode(),
        filename=f'archive-{user}-response.txt')


@gyrobot.command('history')
@click.argument('username')
@click.pass_context
def do_history(ctx, username):
    """\
    Return full user comment history, including deleted comments
    This should work for deleted users as well
    Data comes from pushshift.io"""
    comments = requests.get(
        "http://api.pushshift.io/reddit/comment/search",
        params={
            'limit': 40,
            'author': username,
            'subreddit': subreddit(ctx).display_name}).json()
    if not comments['data']:
        chat(ctx).send_text(f"User u/{username} has no comments in r/{subreddit(ctx).display_name}")
        return
    comment_full_body = [comment['body'] for comment in comments['data']]
    chat(ctx).send_file(
        file_data='\n'.join(comment_full_body).encode(),
        filename=f'comment_history-{username}.txt')


@gyrobot.command('comment_source')
@click.argument('comment_id')
@click.pass_context
def comment_source(ctx, comment_id):
    """Get comment source
    Syntax:
    comment_source comment_thing_id
    comment_source comment_full_url"""
    logger(ctx).debug(comment_id)
    if '/' in comment_id:
        comment_id = praw.reddit.Comment.id_from_url(comment_id)

    try:
        comment = reddit_session(ctx).comment(comment_id)
        comment._fetch()
        chat(ctx).send_file(comment.body.encode('unicode_escape'), filename=f'comment_{comment_id}.md')
    except Exception as e:
        chat(ctx).send_text(repr(e), is_error=True)


@gyrobot.command('deleted_comment_source')
@click.argument('comment_id', nargs=-1)
@click.pass_context
def deleted_comment_source(ctx, comment_ids):
    """\
    Return comment source even if deleted. Use comment ids
    Data comes from pushshift.io"""
    ids = ','.join(comment_ids)
    comments = requests.get(
        "http://api.pushshift.io/reddit/comment/search",
        params={
            'limit': 40,
            'ids': ids,
            'subreddit': subreddit(ctx).display_name}).json()
    if not comments['data']:
        chat(ctx).send_text(f"No comments under those ids were found in r/{subreddit(ctx).display_name}")
        return
    comment_full_body = [comment['body'] for comment in comments['data']]
    chat(ctx).send_file(
        file_data='\n'.join(comment_full_body).encode(),
        filename=f'comment_body-{ids}.txt')


@gyrobot.group('configure_enhanced_crowd_control', cls=ClickAliasedGroup, aliases=['order66', 'order_66'])
@click.pass_context
def configure_enhanced_crowd_control(ctx):
    """Configure the enhanced crowd control

    Syntax:
    list/show: list all current threads
    add THREAD_ID or URL: add a new thread to the monitored threads
    del/delete/remove THREAD_ID or URL: delete the thread from the monitored threads
    """
    config = {}
    config_file = pathlib.Path(f'config/enhanced_crowd_control.yml')
    if config_file.exists():
        with config_file.open(mode='r', encoding='utf8') as y:
            config = dict(yaml.load(y))
    if subreddit(ctx).display_name not in config:
        config[subreddit(ctx).display_name] = {
            'slack': {'channel': '#something', 'url': 'https://hooks.slack.com/services/TEAM_ID/CHANNEL_ID/KEY'},
            'threads': [{'action': 'remove', 'id': 'xxxxxx', 'last': None}]}
        with config_file.open(mode='w', encoding='utf8') as y:
            yaml.dump(config, y)
    monitored_threads: list = config[subreddit(ctx).display_name]['threads']
    ctx.obj['monitored_threads'] = monitored_threads
    ctx.obj['config'] = config
    ctx.obj['config_file'] = config_file


@configure_enhanced_crowd_control.command('list', aliases=['show'])
@click.pass_context
def configure_enhanced_crowd_control_list(ctx):
    monitored_threads = ctx.obj['monitored_threads']
    text = ""
    for thread_index, thread in enumerate(monitored_threads):
        if 'date' in thread and 'permalink' in thread:
            submission_date = thread['date']
            permalink = thread['permalink']
        else:
            s = reddit_session(ctx).submission(thread['id'])
            s.comment_limit = 0
            s._fetch()
            submission_date = datetime.datetime.utcfromtimestamp(s.created_utc)
            permalink = s.permalink
            thread['date'] = submission_date
            thread['permalink'] = permalink
        from_date = thread.get('from_date')
        to_date = thread.get('to_date')
        from_date_text = from_date.isoformat() if from_date else "-\u221e"
        to_date_text = to_date.isoformat() if to_date else "+\u221e"
        action_emoji = '\u274c' if thread['action'] == 'remove' else '\u2611'
        text += (f"{1 + thread_index}. {action_emoji} {reddit_session(ctx).config.reddit_url}{permalink}\t"
                 f"(on {submission_date:%Y-%m-%d %H:%M:%S UTC}) "
                 f"(monitoring {from_date_text} \u2014 {to_date_text})")
        text += "\n"
    chat(ctx).send_text(text)


@configure_enhanced_crowd_control.command('add')
@click.argument('thread_id')
@click.pass_context
def configure_enhanced_crowd_control_add(ctx, thread_id):
    monitored_threads = ctx.obj['monitored_threads']
    thread_id = extract_real_thread_id(thread_id)
    found = [t for t in monitored_threads if t['id'] == thread_id]
    if found:
        chat(ctx).send_text(f"Ignoring addition request, {thread_id} has already been added", is_error=True)
    else:
        s = reddit_session(ctx).submission(thread_id)
        s.comment_limit = 0
        s._fetch()
        submission_date = datetime.datetime.utcfromtimestamp(s.created_utc)
        submission_subreddit = s.subreddit.display_name
        submission_url = reddit_session(ctx).config.reddit_url + s.permalink
        if s.subreddit.display_name.lower() != subreddit(ctx).display_name.lower():
            chat(ctx).send_text(
                f"Cannot add a thread that belongs to r/{submission_subreddit}. ({submission_url})",
                is_error=True)
            return
        permalink = s.permalink
        monitored_threads.append({
            'action': 'remove',
            'id': thread_id,
            'last': None,
            'date': submission_date,
            'permalink': permalink})
        chat(ctx).send_text(f"Added {thread_id} ({submission_url})")

    with ctx.obj['config_file'].open(mode='w', encoding='utf8') as y:
        yaml.dump(ctx.obj['config'], y)


@configure_enhanced_crowd_control.command('del', aliases=['delete', 'remove'])
@click.argument('thread_id')
@click.pass_context
def configure_enhanced_crowd_control_list(ctx, thread_id):
    monitored_threads = ctx.obj['monitored_threads']
    thread_id = extract_real_thread_id(thread_id)
    remove_me = None
    if re.match(r'^\d+$', thread_id):
        remove_me = int(thread_id) - 1
        thread_id = monitored_threads[remove_me]['id']
    else:
        for thread_index, thread in enumerate(monitored_threads):
            if thread['id'] == thread_id:
                remove_me = thread_index
                break
    if remove_me is not None:
        monitored_threads.pop(remove_me)
        chat(ctx).send_text(f"Removed {thread_id}")
    else:
        chat(ctx).send_text(f"{thread_id} not found", is_error=True)

    with ctx.obj['config_file'].open(mode='w', encoding='utf8') as y:
        yaml.dump(ctx.obj['config'], y)


@gyrobot.command('unicode_post')
@click.argument('thread_id')
@click.pass_context
def unicode(ctx, thread_id):
    """Convert reddit post title to unicode code points"""
    thread_id = extract_real_thread_id(thread_id)
    logger(ctx).debug(thread_id)
    logger(ctx).debug(reddit_session(ctx))
    post = reddit_session(ctx).submission(thread_id)
    post._fetch()
    logger(ctx).debug(post.title)
    final_text = ''
    for char in post.title:
        final_text += f"U+{ord(char):06x} {char} {unicodedata.name(char)}\n"
    chat(ctx).send_file(final_text.encode('utf8'), filename='UnicodeAnalysis.txt', title='Unicode')
