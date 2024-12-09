import datetime
import os

import click
import prawcore
from durations_nlp import Duration
from word2number.w2n import word_to_num

from commands import gyrobot, ClickAliasedGroup
from commands.extended_context import ExtendedContext
from commands.reddit.common import extract_real_thread_id, extract_username
from state_file import state_file

if 'SUBREDDIT_NAME' not in os.environ:
    raise ImportError('SUBREDDIT_NAME not found in environment')


@gyrobot.group('nuke', cls=ClickAliasedGroup)
def nuke():
    pass


@nuke.command('thread')
@click.argument('thread_id')
@click.pass_context
def nuke_thread(ctx: ExtendedContext, thread_id):
    """Nuke whole thread (except distinguished comments)
    Thread ID should be either the submission URL or the submission id"""
    thread_id = extract_real_thread_id(thread_id)
    post = ctx.reddit_session.submission(thread_id)
    post.comments.replace_more(limit=None)
    comments = post.comments.list()
    post.mod.remove()
    comments_removed = []
    comments_distinguished = 0
    comments_already_removed = 0
    for comment in comments:
        if comment.distinguished:
            comments_distinguished += 1
            continue
        if comment.banned_by:
            comments_already_removed += 1
            continue
        comment.mod.remove()
        comments_removed.append(comment.id)
    post.mod.lock()
    result = (
        f"{len(comments_removed)} comments were removed.\n"
        f"{comments_distinguished} distinguished comments were kept.\n"
        f"{comments_already_removed} comments were already removed.\n"
        "Submission was locked")
    with state_file('nuke_thread') as state:
        state[thread_id] = comments_removed
    ctx.chat.send_text(result)


@nuke.command('thread_undo')
@click.argument('thread_id')
@click.pass_context
def undo_nuke_thread(ctx: ExtendedContext, thread_id):
    """Undo previous nuking of a thread

    :param ctx: command context
    :param thread_id: either the submission URL or the submission id"""
    thread_id = extract_real_thread_id(thread_id)
    with state_file('nuke_thread') as state:
        if thread_id not in state:
            ctx.chat.send_text(f"Could not find thread {thread_id}", is_error=True)
            return
        removed_comments = state.pop(thread_id)
        for comment_id in removed_comments:
            comment = ctx.reddit_session.comment(comment_id)
            comment.mod.approve()
        ctx.chat.send_text(f"Nuking {len(removed_comments)} comments was undone")


def _w2n(input_text):
    try:
        return word_to_num(input_text)
    except ValueError:
        return None


@nuke.command('user')
@click.argument('username')
@click.argument('timeframe', required=False, nargs=-1)
@click.option('-s', '-p', '--submissions', '--posts', 'remove_submissions',
              is_flag=True, default=False, type=click.BOOL)
@click.pass_context
def nuke_user(ctx: ExtendedContext, username: str, timeframe: tuple[str] = None, remove_submissions: bool = False):
    """\
    Nuke the comments of a user. Append the timeframe to search.
    Default value is 24 hours. You can use standard values, e.g. "48 hours", "2 months", "10 years" etc.
    Add SUBMISSIONS or POSTS to remove submissions as well.
    """
    if not timeframe:
        timeframe = ('24', 'hours')
    if timeframe[0] in ('a', 'an'):
        timeframe = ('1',) + timeframe[1:]
    elif (conv_num := _w2n(timeframe[0])) is not None:
        timeframe = (str(conv_num),) + timeframe[1:]
    if timeframe in (('forever_and_ever',), ('forever', 'and', 'ever'), ('forever',)):
        timeframe = ('100', 'years')  # should be enough
    timeframe = ' '.join(timeframe)
    timeframe = ' '.join(timeframe.replace('_', ' ').split())
    cutoff_age = Duration(timeframe)
    if not cutoff_age.parsed_durations:
        ctx.chat.send_text(f'{timeframe} is not an acceptable timeframe', is_error=True)
        return
    if (username := extract_username(username)) is None:
        ctx.chat.send_text(f'{username} is not a valid username', is_error=True)
        return
    u = ctx.bot_reddit_session.redditor(username)
    try:
        u._fetch()
    except prawcore.exceptions.ResponseException as ex:
        if ex.response.status_code == 400:
            ctx.chat.send_text(f'{username} may be shadowbanned', is_error=True)
            return
        elif ex.response.status_code == 404:
            ctx.chat.send_text(f'{username} not found', is_error=True)
            return
        raise
    if hasattr(u, 'is_suspended') and u.is_suspended:
        ctx.chat.send_text(f"{username} is suspended", is_error=True)

    all_comments = u.comments.new(limit=None)
    removed_comments = 0
    other_subreddits = 0
    already_removed = 0
    too_old = 0
    other_subreddit_history = {}
    now = datetime.datetime.utcnow()

    result = ""

    try:
        all_comments = list(all_comments)
    except prawcore.exceptions.Forbidden as ex:
        ctx.chat.send_text(f"User `{username}` is probably suspended", is_error=True)
        ctx.logger.warning(repr(ex))
        return
    except Exception as ex:
        ctx.logger.warning(type(ex))
        all_comments = []

    for c in all_comments:
        comment_subreddit_name = c.subreddit.display_name.lower()
        if comment_subreddit_name != ctx.subreddit.display_name.lower():
            other_subreddits += 1
            other_subreddit_history[comment_subreddit_name] = \
                other_subreddit_history.get(comment_subreddit_name, 0) + 1
            continue
        if c.banned_by and c.banned_by != 'AutoModerator':
            already_removed += 1
            continue
        comment_created = datetime.datetime.fromtimestamp(c.created_utc)
        comment_age = now - comment_created
        if comment_age.days > cutoff_age.to_days():
            too_old += 1
            continue
        c.mod.remove()
        removed_comments += 1
    result += (
        f"Removed {removed_comments} comments.\n"
        f"{other_subreddits} comments in other subreddits.\n"
        f"{already_removed} comments were already removed.\n"
        f"{too_old} comments were too old for the {timeframe} ({cutoff_age.to_days()} d) timeframe.\n"
    )
    if remove_submissions:
        all_submissions = u.submissions.new(limit=None)
        already_removed_submissions = 0
        removed_submissions = 0
        other_subreddit_submissions = 0
        too_old_submissions = 0
        for s in all_submissions:
            submission_subreddit_name = s.subreddit.display_name.lower()
            if submission_subreddit_name != ctx.subreddit.display_name.lower():
                other_subreddits += 1
                other_subreddit_history[submission_subreddit_name] = \
                    other_subreddit_history.get(submission_subreddit_name, 0) + 1
                continue
            if s.banned_by and s.banned_by != 'AutoModerator':
                already_removed_submissions += 1
                continue
            submission_created = datetime.datetime.fromtimestamp(s.created_utc)
            submission_age = now - submission_created
            if submission_age.days > cutoff_age.to_days():
                too_old += 1
                continue
            s.mod.remove()
            removed_submissions += 1
        result += (
            f"Removed {removed_submissions} submissions.\n"
            f"{other_subreddit_submissions} submissions in other subreddits.\n"
            f"{already_removed_submissions} submissions were already removed.\n"
            f"{too_old_submissions} submissions were too old for the {timeframe} timeframe.\n"
        )
    ctx.chat.send_text(result)


@nuke.command('ghosts', aliases=['ghost'])
@click.argument('thread_id')
@click.pass_context
def nuke_ghosts(ctx: ExtendedContext, thread_id):
    """Nuke deleted users in thread.
    :parameter: thread_id either the submission URL or the submission id"""
    thread_id = extract_real_thread_id(thread_id)
    submission = ctx.reddit_session.submission(thread_id)
    submission.comments.replace_more(limit=None)

    removed_comments = []

    for comment in submission.comments.list():
        if comment.distinguished:  # comment was from mod
            continue
        if comment.banned_by:  # comment was already removed
            continue
        if comment.author:  # author exists
            continue
        removed_comments.append({
            'Id': comment.id,
            'Link': ctx.reddit_session.config.reddit_url + comment.permalink,
            'Text': comment.body})
        comment.mod.remove()
    ctx.chat.send_text(f"{len(removed_comments)} comments were removed.\n")
    ctx.chat.send_table(title="Removed Comments", table=removed_comments, send_as_excel=True)
