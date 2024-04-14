import base64
import datetime
import io
import logging
import uuid
import zipfile
from abc import ABC, abstractmethod
from io import BytesIO
from typing import List, Dict, Callable

import pandas as pd
from tabulate import tabulate


class Conversation(ABC):
    channel_id: str
    channel_name: str
    user_id: str
    team_id: str

    def __init__(self, bot_name, channel_id, user_id, team_id):
        self.bot_name = bot_name
        self.channel_id = channel_id
        self.user_id = user_id
        self.team_id = team_id

    @abstractmethod
    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        pass

    @abstractmethod
    def send_table(self, title: str, table: List[Dict], send_as_excel: bool = False) -> None:
        pass

    @abstractmethod
    def send_tables(self, title: str, tables: Dict[str, List[Dict]], send_as_excel: bool = False) -> None:
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

    @abstractmethod
    def get_user_info(self, user_id) -> Dict:
        pass

    @abstractmethod
    def get_team_info(self) -> Dict:
        pass

    @property
    def team_name(self) -> str:
        return self.get_team_info()['name']

    @staticmethod
    def make_excel_table(table):
        table_output: BytesIO
        with io.BytesIO() as table_output:
            table_df = pd.DataFrame(table)
            Conversation.localize_datetime(table_df)
            # noinspection PyTypeChecker
            table_df.reset_index(drop=True).to_excel(table_output)
            excel_data = table_output.getvalue()
        return excel_data

    @staticmethod
    def localize_datetime(table_df):
        dt_cols = table_df.select_dtypes(include=['datetime64[ns, UTC]']).columns
        for col in dt_cols:
            table_df[col] = table_df[col].dt.tz_localize(None)

    @staticmethod
    def plain_text_table_sequence(tables: Dict[str, List[Dict]]) -> str:
        result = ''
        for table_name, table in tables.items():
            table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline', maxcolwidths=64)
            # table_markdown = tabulate(table, headers='keys', tablefmt='pipe', maxcolwidths=30)
            table_length = len(table_name)
            result += "╒" + "═" * (2 + table_length) + "╕" + "\n"
            result += "│ " + table_name + " │\n"
            result += "╞" + table_markdown[1:3 + table_length] + "╧"
            result += table_markdown[4 + table_length:]
            result += "\n\n"
        return result

    @staticmethod
    def zipped_markdown_from_tables(tables):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for table_name, table in tables.items():
                table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline')
                zip_file.writestr(f"{table_name}.md", table_markdown.encode())
        zip_data = zip_buffer.getvalue()
        return zip_data

    @staticmethod
    def excel_from_tables(tables):
        excel_output: BytesIO
        with io.BytesIO() as excel_output:
            # noinspection PyTypeChecker
            with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
                long_sheet_names = []
                for table_name, table in tables.items():
                    if len(table_name) <= 31:
                        sheet_name = table_name
                    else:
                        sheet_name = Conversation.random_name()
                        long_sheet_names.append({'Original Name': table_name, 'Translated Name': sheet_name})
                    table_df = pd.DataFrame(table)
                    Conversation.localize_datetime(table_df)
                    table_df.reset_index(drop=True).to_excel(writer, sheet_name=sheet_name)
                if long_sheet_names:
                    table_sheet_names = pd.DataFrame(long_sheet_names)
                    table_sheet_names.reset_index(drop=True).to_excel(writer, sheet_name='__LongNames')
            excel_output.seek(0)
            excel_data = excel_output.read()
        return excel_data

    @staticmethod
    def random_name() -> str:
        random_bytes = uuid.uuid4().bytes
        shorter_text = base64.b64encode(random_bytes)
        cleaned_up_text = shorter_text.strip(b'=').replace(b'/', b'.')
        return cleaned_up_text.decode()


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
