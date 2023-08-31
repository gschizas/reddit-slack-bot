from abc import ABC, abstractmethod


class ChatWrapper(ABC):
    message_handler = None

    def __init__(self, bot_name, message_handler):
        self.bot_name = bot_name
        ChatWrapper.message_handler = message_handler
        self.users = {}
        self.teams = {}
        self.channels = {}
        self.web_client = None
        self.team_id = None
        self.channel_id = None
        self.user_id = None
        self.message = None
        self.permalink = None

    @abstractmethod
    def send_text(self, text, is_error: bool = False, icon_emoji: str = None) -> None:
        pass

    @abstractmethod
    def send_ephemeral(self, text, blocks, is_error, icon_emoji):
        pass

    @abstractmethod
    def send_file(self, file_data, title, filename, filetype):
        pass

    @abstractmethod
    def send_fields(self, text, fields):
        pass

    @abstractmethod
    def send_blocks(self, blocks):
        pass

    @abstractmethod
    def start(self):
        pass

    @staticmethod
    @abstractmethod
    def handle_message(**payload):
        pass

    @abstractmethod
    def load(self, web_client, team_id, channel_id, user_id, msg, permalink):
        pass

    @abstractmethod
    def preload(self, user_id, team_id, channel_id):
        pass

    @abstractmethod
    def connect(self):
        pass

    @property
    @abstractmethod
    def channel_name(self):
        pass
