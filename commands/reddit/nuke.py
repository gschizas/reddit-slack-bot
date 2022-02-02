import datetime

import click
import prawcore

from commands import gyrobot, reddit_session, chat, bot_reddit_session, logger, subreddit
from commands.reddit.common import extract_real_thread_id, extract_username
from state_file import state_file


@gyrobot.group('nuke')
def nuke():
    pass


@nuke.command('thread')
@click.argument('thread_id')
@click.pass_context
def nuke_thread(ctx, thread_id):
    """Nuke whole thread (except distinguished comments)
    Thread ID should be either the submission URL or the submission id"""
    thread_id = extract_real_thread_id(thread_id)
    post = reddit_session(ctx).submission(thread_id)
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
    chat(ctx).send_text(result)


@nuke.command('thread_undo')
@click.argument('thread_id')
@click.pass_context
def undo_nuke_thread(ctx, thread_id):
    """Undo previous nuke thread
    Thread ID should be either the submission URL or the submission id"""
    thread_id = extract_real_thread_id(thread_id)
    with state_file('nuke_thread') as state:
        if thread_id not in state:
            chat(ctx).send_text(f"Could not find thread {thread_id}", is_error=True)
            return
        removed_comments = state.pop(thread_id)
        for comment_id in removed_comments:
            comment = reddit_session(ctx).comment(comment_id)
            comment.mod.approve()
        chat(ctx).send_text(f"Nuking {len(removed_comments)} comments was undone")


CUTOFF_AGES = {'24': 1, '48': 2, '72': 3, 'A_WEEK': 7, 'TWO_WEEKS': 14, 'A_MONTH': 30, 'THREE_MONTHS': 90,
               'FOREVER_AND_EVER': 36525}


@nuke.command('user')
@click.argument('username')
@click.argument('timeframe', required=False, type=click.Choice(list(CUTOFF_AGES.keys()), case_sensitive=False))
@click.option('-s', '-p', '--submissions', '--posts', 'remove_submissions', default=False, type=click.BOOL)
@click.pass_context
def nuke_user(ctx, username: str, timeframe: str = None, remove_submissions: bool = False):
    """\
    Nuke the comments of a user. Append the timeframe to search.
    Accepted values are 24 (default), 48, 72, A_WEEK, TWO_WEEKS, A_MONTH, THREE_MONTHS, FOREVER_AND_EVER
    Add SUBMISSIONS or POSTS to remove submissions as well.
    """
    # FOREVER_AND_EVER is 100 years. Should be enough.

    timeframe = timeframe or '24'
    if timeframe not in CUTOFF_AGES:
        chat(ctx).send_text(f'{timeframe} is not an acceptable timeframe', is_error=True)
        return
    if (username := extract_username(username)) is None:
        chat(ctx).send_text(f'{username} is not a valid username', is_error=True)
        return
    u = bot_reddit_session(ctx).redditor(username)
    try:
        u._fetch()
    except prawcore.exceptions.ResponseException as ex:
        if ex.response.status_code == 400:
            chat(ctx).send_text(f'{username} may be shadowbanned', is_error=True)
            return
        elif ex.response.status_code == 404:
            chat(ctx).send_text(f'{username} not found', is_error=True)
            return
        raise
    if hasattr(u, 'is_suspended') and u.is_suspended:
        chat(ctx).send_text(f"{username} is suspended", is_error=True)

    all_comments = u.comments.new(limit=None)
    removed_comments = 0
    other_subreddits = 0
    already_removed = 0
    too_old = 0
    other_subreddit_history = {}
    cutoff_age = CUTOFF_AGES[timeframe]
    now = datetime.datetime.utcnow()

    result = ""

    try:
        all_comments = list(all_comments)
    except prawcore.exceptions.Forbidden as ex:
        chat(ctx).send_text(f"User `{username}` is probably suspended", is_error=True)
        return
    except Exception as ex:
        logger(ctx).warn(type(ex))
        all_comments = []

    for c in all_comments:
        comment_subreddit_name = c.subreddit.display_name.lower()
        if comment_subreddit_name != subreddit(ctx).display_name.lower():
            other_subreddits += 1
            other_subreddit_history[comment_subreddit_name] = \
                other_subreddit_history.get(comment_subreddit_name, 0) + 1
            continue
        if c.banned_by and c.banned_by != 'AutoModerator':
            already_removed += 1
            continue
        comment_created = datetime.datetime.fromtimestamp(c.created_utc)
        comment_age = now - comment_created
        if comment_age.days > cutoff_age:
            too_old += 1
            continue
        c.mod.remove()
        removed_comments += 1
    result += (
        f"Removed {removed_comments} comments.\n"
        f"{other_subreddits} comments in other subreddits.\n"
        f"{already_removed} comments were already removed.\n"
        f"{too_old} comments were too old for the {timeframe} timeframe.\n"
    )
    if remove_submissions:
        all_submissions = u.submissions.new(limit=None)
        already_removed_submissions = 0
        removed_submissions = 0
        other_subreddit_submissions = 0
        too_old_submissions = 0
        for s in all_submissions:
            submission_subreddit_name = s.subreddit.display_name.lower()
            if submission_subreddit_name != subreddit(ctx).display_name.lower():
                other_subreddits += 1
                other_subreddit_history[submission_subreddit_name] = \
                    other_subreddit_history.get(submission_subreddit_name, 0) + 1
                continue
            if s.banned_by and s.banned_by != 'AutoModerator':
                already_removed_submissions += 1
                continue
            submission_created = datetime.datetime.fromtimestamp(s.created_utc)
            submission_age = now - submission_created
            if submission_age.days > cutoff_age:
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
    chat(ctx).send_text(result)