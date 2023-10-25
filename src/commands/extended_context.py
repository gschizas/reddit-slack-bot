import logging

import click
import praw

from chat import ChatWrapper


class ExtendedContext(click.Context):
    @property
    def chat(self) -> ChatWrapper:
        return self.obj['chat']

    @property
    def logger(self) -> logging.Logger:
        return self.obj['logger']

    @property
    def subreddit(self) -> praw.reddit.Subreddit:
        return self.obj['subreddit']

    @property
    def reddit_session(self) -> praw.reddit.Reddit:
        return self.obj['reddit_session']

    @property
    def bot_reddit_session(self) -> praw.reddit.Reddit:
        return self.obj['bot_reddit_session']
