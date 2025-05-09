import datetime
import logging
import os
from typing import List, Dict, Callable

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from tabulate import tabulate

from chat.chat_wrapper import Conversation, Message

teams_cache = {}
users_cache = {}
channels_cache = {}

handle_message: Callable
logger: logging.Logger

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

class SlackConversation(Conversation):
    @property
    def channel_name(self):
        return channels_cache[self.team_id].get(self.channel_id)

    def send_text(self, text, is_error=False, icon_emoji=None, channel=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        app.client.chat_postMessage(
            channel=channel or self.channel_id,
            text=text,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_table(self, title: str, table: List[Dict], send_as_excel: bool = False) -> None:
        if send_as_excel or os.environ.get('SEND_TABLES_AS_EXCEL', '').lower() in ['true', '1', 't', 'y', 'yes']:
            excel_data = self.make_excel_table(table)
            self.send_file(excel_data, filename=f'{title}.xlsx')
        else:
            table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline')
            self.send_file(file_data=table_markdown.encode(), filename=f'{title}.txt')

    def send_tables(self, title: str, tables: Dict[str, List[Dict]], send_as_excel: bool = False) -> None:
        if send_as_excel or os.environ.get('SEND_TABLES_AS_EXCEL', '').lower() in ['true', '1', 't', 'y', 'yes']:
            excel_data = self.excel_from_tables(tables)
            self.send_file(excel_data, filename=f'{title}.xlsx')
        else:
            result = self.plain_text_table_sequence(tables)
            self.send_file(file_data=result.encode(), filename=f'{title}.txt')
            # zip_data = self.zipped_markdown_from_tables(tables)
            # self.send_file(zip_data, filename=f'{title}.zip')

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        app.client.chat_postEphemeral(
            channel=self.channel_id,
            blocks=blocks,
            text=text,
            user=self.user_id,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_file(self, file_data, title=None, filename=None, channel=None):
        try:
            app.client.files_upload_v2(
                channel=channel or self.channel_id,
                icon_emoji=':robot_face:',
                username=self.bot_name,
                file=file_data,
                filename=filename,
                title=title)
        except Exception as ex:
            self.send_text(text=f"Error while uploading {filename}:\n```{ex!r}```", is_error=True)

    def send_fields(self, text, fields):
        app.client.chat_postMessage(
            channel=self.channel_id,
            icon_emoji=':robot_face:',
            text=text,
            username=self.bot_name,
            attachments=fields)

    def send_blocks(self, blocks):
        app.client.chat_postMessage(
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
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()


def _slack_user_info(user_id):
    if user_id not in users_cache:
        response_user = app.client.users_info(user=user_id)
        if response_user['ok']:
            users_cache[user_id] = response_user['user']


def _slack_team_info(team_id):
    if team_id not in teams_cache:
        response_team = app.client.team_info()
        if response_team['ok']:
            teams_cache[team_id] = response_team['team']


def _slack_channel_info(team_id, channel_id):
    if team_id not in channels_cache:
        channels_cache[team_id] = {}
    if channel_id not in channels_cache[team_id]:
        response_channel = app.client.conversations_info(channel=channel_id)
        channel_info = response_channel['channel'] if response_channel['ok'] else {}
        if channel_info.get('is_group') or channel_info.get('is_channel'):
            priv = '🔒' if channel_info.get('is_private') else '#'
            channels_cache[team_id][channel_id] = priv + channel_info['name_normalized']
        elif channel_info.get('is_im'):
            response_members = app.client.conversations_members(channel=channel_id)
            for user_id in response_members['members']:
                _slack_user_info(user_id)
            participants = [f"{users_cache[user_id]['real_name']} <{users_cache[user_id]['name']}@{user_id}>"
                            for user_id in response_members['members']]
            channels_cache[team_id][channel_id] = '🧑' + ' '.join(participants)


def _preload(user_id, team_id, channel_id):
    _slack_team_info(team_id)
    _slack_user_info(user_id)
    _slack_channel_info(team_id, channel_id)


@app.event("message")
def handle_slack_message(event, say):
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
    permalink_raw = app.client.chat_getPermalink(channel=channel_id, message_ts=event['ts'])
    permalink = permalink_raw['permalink']

    conversation = SlackConversation(bot_name, channel_id, user_id, team_id)
    message: Message = Message(conversation, timestamp, permalink, event['text'])
    handle_message(message)
