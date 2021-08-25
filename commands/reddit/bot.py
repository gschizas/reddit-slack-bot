import click

from commands import gyrobot, bot_reddit_session, subreddit, chat

WIKI_PAGE_BAD_FORMAT = "Page should have a title (starting with `# `) at the first line and an empty line below that"


def _get_wiki_text(sr, wiki_page_name, revision_id=None):
    if revision_id is None: revision_id = 'LATEST'
    wiki_page = sr.wiki[wiki_page_name]
    # If wiki page is not protected (i.e. "Only mods may edit and view"), protect it.
    if wiki_page.mod.settings()['permlevel'] != 2:
        wiki_page.mod.update(permlevel=2, listed=True)
    wiki_text = wiki_page.content_md if revision_id == 'LATEST' else wiki_page.revision[revision_id].content_md
    wiki_lines = wiki_text.splitlines()
    return wiki_lines


@gyrobot.group('make')
def make():
    pass


@make.command('post')
@click.argument('thread_id')
@click.argument('wiki_page')
@click.argument('revision_id', required=False)
@click.pass_context
def make_post(ctx, thread_id, wiki_page_name, revision_id=None):
    """
    Create or update a post as the common moderator user. It reads the provided wiki page and creates or updates
    a post according to the included data.

    Note that there's no need for a separate wiki page for each post, the wiki page can be reused

    Syntax:
    make_post NEW wiki_page
    make_post thread_id wiki_page
    make_post thread_id wiki_page version_id"""

    revision_id = revision_id or 'LATEST'

    sr = bot_reddit_session(ctx).subreddit(subreddit(ctx).display_name)
    wiki_lines = _get_wiki_text(sr, wiki_page_name, revision_id)
    if len(wiki_lines) < 2:
        chat(ctx).send_text(WIKI_PAGE_BAD_FORMAT, is_error=True)
        return
    if wiki_lines[0].startswith("# ") and wiki_lines[1] == '':
        wiki_title = wiki_lines[0][2:]
        wiki_text_body = '\n'.join(wiki_lines[2:])
    else:
        chat(ctx).send_text(WIKI_PAGE_BAD_FORMAT, is_error=True)
        return

    if thread_id.upper() == 'NEW':
        submission = sr.submit(wiki_title, wiki_text_body)
        submission.mod.distinguish(how='yes', sticky=True)
        chat(ctx).send_text(bot_reddit_session(ctx).config.reddit_url + submission.permalink)
    else:
        submission = self.bot_reddit_session.submission(thread_id)
        submission.edit(wiki_text_body)
        chat(ctx).send_text(bot_reddit_session(ctx).config.reddit_url + submission.permalink)


@make.command('sticky')
@click.argument('thread_id')
@click.argument('wiki_page')
@click.argument('revision_id', required=False)
@click.pass_context
def make_sticky(ctx, thread_id, wiki_page, revision_id=None):
    """
    Create or update a sticky comment as the common moderator user. It reads the provided wiki page and creates or
    updates the comment according to the included data.

    Note that there's no need for a separate wiki page for each post, the wiki page can be reused

    Syntax:
    make_sticky thread_id wiki_page
    make_sticky thread_id wiki_page version_id"""
    revision_id = revision_id or 'LATEST'

    sr = bot_reddit_session(ctx).subreddit(subreddit(ctx).display_name)
    wiki_lines = _get_wiki_text(sr, wiki_page, revision_id)
    wiki_text_body = '\n'.join(wiki_lines)

    submission = bot_reddit_session(ctx).submission(thread_id)
    sticky_comments = [c for c in submission.comments.list()
                       if getattr(c, 'stickied', False) and
                       c.author.name == self.bot_reddit_session.user.me().name]
    if sticky_comments:
        sticky_comment = sticky_comments[0]
        sticky_comment.edit(wiki_text_body)
    else:
        sticky_comment = submission.reply(wiki_text_body)
        sticky_comment.mod.distinguish(how='yes', sticky=True)

    chat(ctx).send_text(bot_reddit_session(ctx).config.reddit_url + sticky_comment.permalink)
