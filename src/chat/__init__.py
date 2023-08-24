import os
from typing import Callable

from chat.chat_wrapper import ChatWrapper
from chat.slack import SlackWrapper


def get_chat_wrapper(bot_name: str, message_handler: Callable) -> ChatWrapper:
    if 'SLACK_API_TOKEN' in os.environ:
        return SlackWrapper(bot_name, message_handler)
    elif 'DISCORD_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    elif 'TEAMS_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    elif 'TELEGRAM_API_TOKEN' in os.environ:
        raise NotImplementedError("Not implemented yet!")
    else:
        raise NotImplementedError("Unknown chat protocol")
