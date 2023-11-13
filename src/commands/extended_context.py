import logging

import click
import praw

from chat.chat_wrapper import ChatWrapper, Message, Conversation


class ExtendedContext(click.Context):

    @property
    def chat_wrapper(self) -> ChatWrapper:
        return self.obj['chat_wrapper']

    @property
    def chat(self) -> Conversation:
        return self.obj['message'].conversation

    @property
    def message(self) -> Message:
        return self.obj['message']

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
