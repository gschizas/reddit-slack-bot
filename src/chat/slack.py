import datetime
import io
import logging
import os
import zipfile
from typing import List, Dict, Callable

import pandas as pd
from slack_sdk.errors import SlackApiError
from slack_sdk.rtm_v2 import RTMClient
from slack_sdk.web import WebClient
from tabulate import tabulate

from chat.chat_wrapper import Conversation, Message

slack_client: RTMClient = RTMClient(token=os.environ['SLACK_API_TOKEN'], proxy=os.environ.get('HTTPS_PROXY'))
web_client: WebClient = WebClient(token=os.environ['SLACK_API_TOKEN'], proxy=os.environ.get('HTTPS_PROXY'))

teams_cache = {}
users_cache = {}
channels_cache = {}

bot_name: str
handle_message: Callable
logger: logging.Logger


class SlackConversation(Conversation):
    @property
    def channel_name(self):
        return channels_cache[self.team_id].get(self.channel_id)

    def send_text(self, text, is_error=False, icon_emoji=None, channel=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        web_client.chat_postMessage(
            channel=channel or self.channel_id,
            text=text,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_table(self, title: str, table: List[Dict], send_as_excel: bool = False) -> None:
        if send_as_excel or os.environ.get('SEND_TABLES_AS_EXCEL', '').lower() in ['true', '1', 't', 'y', 'yes']:
            with io.BytesIO() as table_output:
                table_df = pd.DataFrame(table)
                table_df.reset_index(drop=True).to_excel(table_output)
                self.send_file(table_output.getvalue(), filename=f'{title}.xlsx')
        else:
            table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline')
            self.send_file(file_data=table_markdown.encode(), filename=f'{title}.md')

    def send_tables(self, title: str, tables: Dict[str, List[Dict]], send_as_excel: bool = False) -> None:
        if send_as_excel or os.environ.get('SEND_TABLES_AS_EXCEL', '').lower() in ['true', '1', 't', 'y', 'yes']:
            with io.BytesIO() as excel_output:
                with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
                    for table_name, table in tables.items():
                        table_df = pd.DataFrame(table)
                        table_df.reset_index(drop=True).to_excel(writer, sheet_name=table_name)
                    writer.save()
                excel_output.seek(0)
                excel_data = excel_output.read()
                self.send_file(excel_data, filename=f'{title}.xlsx')
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for table_name, table in tables.items():
                    table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline')
                    zip_file.writestr(f"{table_name}.md", table_markdown.encode())
            self.send_file(zip_buffer.getvalue(), filename=f'{title}.zip')

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        web_client.chat_postEphemeral(
            channel=self.channel_id,
            blocks=blocks,
            text=text,
            user=self.user_id,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_file(self, file_data, title=None, filename=None, channel=None):
        try:
            web_client.files_upload_v2(
                channel=channel or self.channel_id,
                icon_emoji=':robot_face:',
                username=self.bot_name,
                file=file_data,
                filename=filename,
                title=title)
        except SlackApiError as ex:
            self.send_text(text=f"Error while uploading {filename}:\n```{ex!r}```", is_error=True)

    def send_fields(self, text, fields):
        web_client.chat_postMessage(
            channel=self.channel_id,
            icon_emoji=':robot_face:',
            text=text,
            username=self.bot_name,
            attachments=fields)

    def send_blocks(self, blocks):
        web_client.chat_postMessage(
            channel=self.channel_id,
            icon_emoji=':robot_face:',
            blocks=blocks,
            username=self.bot_name)

    def get_user_info(self, user_id):
        _slack_user_info(user_id)
        return users_cache[user_id]

    def get_team_info(self):
        _slack_team_info(team_id=self.team_id)
        return teams_cache[self.team_id]


def chat_connect(a_bot_name, a_line_handler):
    global bot_name, line_handler, logger
    bot_name = a_bot_name
    line_handler = a_line_handler
    slack_client.start()


def _slack_user_info(user_id):
    if user_id not in users_cache:
        response_user = web_client.users_info(user=user_id)
        if response_user['ok']:
            users_cache[user_id] = response_user['user']


def _slack_team_info(team_id):
    if team_id not in teams_cache:
        response_team = web_client.team_info()
        if response_team['ok']:
            teams_cache[team_id] = response_team['team']


def _slack_channel_info(team_id, channel_id):
    if team_id not in channels_cache:
        channels_cache[team_id] = {}
    if channel_id not in channels_cache[team_id]:
        response_channel = web_client.conversations_info(channel=channel_id)
        channel_info = response_channel['channel'] if response_channel['ok'] else {}
        if channel_info.get('is_group') or channel_info.get('is_channel'):
            priv = '🔒' if channel_info.get('is_private') else '#'
            channels_cache[team_id][channel_id] = priv + channel_info['name_normalized']
        elif channel_info.get('is_im'):
            response_members = web_client.conversations_members(channel=channel_id)
            for user_id in response_members['members']:
                _slack_user_info(user_id)
            participants = [f"{users_cache[user_id]['real_name']} <{users_cache[user_id]['name']}@{user_id}>"
                            for user_id in response_members['members']]
            channels_cache[team_id][channel_id] = '🧑' + ' '.join(participants)


def _preload(user_id, team_id, channel_id):
    _slack_team_info(team_id)
    _slack_user_info(user_id)
    _slack_channel_info(team_id, channel_id)


@slack_client.on(event_type='message')
def handle_slack_message(client: RTMClient, event: dict):
    global logger
    if event.get('subtype') in (
            'message_deleted', 'message_replied', 'file_share', 'bot_message', 'slackbot_response'):
        logger.debug(f"Found message of subtype {event.get('subtype')}")
        return
    if 'message' in event:
        event.update(event['message'])
        del event['message']

    channel_id = event['channel']
    team_id = event.get('team', '')
    user_id = event.get('user', '')

    _preload(user_id, team_id, channel_id)

    timestamp = datetime.datetime.fromtimestamp(float(event['ts']))
    permalink_raw = web_client.chat_getPermalink(channel=channel_id, message_ts=event['ts'])
    permalink = permalink_raw['permalink']

    conversation = SlackConversation(bot_name, channel_id, user_id, team_id)
    message: Message = Message(conversation, timestamp, permalink, event['text'])
    handle_message(message)
