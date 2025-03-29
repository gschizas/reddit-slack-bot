import os
from typing import Callable

from chat.chat_wrapper import ChatWrapper


def get_chat_wrapper(logger, bot_name: str, message_handler: Callable) -> ChatWrapper:
    if 'SLACK_API_TOKEN' in os.environ:
        import chat.slack
        connect = chat.slack.chat_connect
        chat.slack.handle_message = message_handler
        chat.slack.logger = logger
    elif 'DISCORD_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    elif 'TEAMS_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    elif 'TELEGRAM_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    elif 'MATTERMOST_API_TOKEN' in os.environ:
        import chat.mattermost
        connect = chat.mattermost.chat_connect
        chat.mattermost.handle_message = message_handler
        chat.mattermost.logger = logger
    else:
        raise NotImplementedError("Unknown chat protocol")
    return ChatWrapper(bot_name, message_handler, connect, logger)
