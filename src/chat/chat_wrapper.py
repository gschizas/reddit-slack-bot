import datetime
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Callable


class Conversation(ABC):
    channel_id: str
    channel_name: str
    user_id: str

    @abstractmethod
    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        pass

    @abstractmethod
    def send_table(self, title: str, table: List[Dict], send_as_excel: bool = False) -> None:
        pass

    @abstractmethod
    def send_ephemeral(self, text, blocks, is_error, icon_emoji):
        pass

    @abstractmethod
    def send_file(self, file_data, title=None, filename=None, channel=None):
        pass

    @abstractmethod
    def send_fields(self, text, fields):
        pass

    @abstractmethod
    def send_blocks(self, blocks):
        pass


class Message:
    conversation: Conversation
    timestamp: datetime.datetime
    permalink: str
    text: str

    def __init__(self, conversation: Conversation, timestamp: datetime.datetime, permalink: str, text: str):
        self.conversation = conversation
        self.timestamp = timestamp
        self.permalink = permalink
        self.text = text


class ChatWrapper(ABC):
    text_handler: Callable = None
    start_handler: Callable = None
    bot_name: str

    def __init__(self, bot_name: str, text_handler: Callable, start_handler: Callable, logger: logging.Logger):
        self.bot_name = bot_name
        self.text_handler = text_handler
        self.start_handler = start_handler
        self.logger = logger

    def start(self):
        self.start_handler(self.bot_name, self.handle_message)

    @staticmethod
    def handle_message(message: Message, logger: logging.Logger):
        try:
            ChatWrapper.text_handler(message)
        except Exception as ex:
            logger.exception(f"Error while handling message {message}: {ex!r}")
