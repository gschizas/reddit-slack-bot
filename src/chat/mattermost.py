import datetime
import logging
import os
import json
import traceback

from typing import List, Dict, Callable

import requests
from tabulate import tabulate
from mattermostdriver import Driver

from chat.chat_wrapper import Conversation, Message

teams_cache = {}
users_cache = {}
channels_cache = {}

bot_name: str
handle_message: Callable
logger: logging.Logger
mattermost_client: Driver

class MattermostConversation(Conversation):
    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        mattermost_client.posts.create_post({
            "channel_id": channel or self.channel_id,
            "message": text
        })

    def send_table(self, title: str, table: List[Dict], send_as_excel: bool = False) -> None:
        table_markdown = tabulate(table, headers='keys', tablefmt='pipe')
        mattermost_client.posts.create_post({
            "channel_id": self.channel_id,
            "message": table_markdown
        })

    def send_tables(self, title: str, tables: Dict[str, List[Dict]], send_as_excel: bool = False) -> None:
        full_text = "### "  + title + "\n"
        for table_title, table in tables.items():
            full_text += '#### ' + table_title + '\n'
            full_text += tabulate(table, headers='keys', tablefmt='pipe') + "\n"
        mattermost_client.posts.create_post({
            "channel_id": self.channel_id,
            "message": full_text
        })

    def send_ephemeral(self, text, blocks, is_error, icon_emoji):
        mattermost_client.posts.create_ephemeral_post({
            "channel_id": self.channel_id,
            "message": text
        })

    def send_file(self, file_data, title=None, filename=None, channel=None):
        pass

    def send_fields(self, text, fields):
        pass

    def send_blocks(self, blocks):
        pass

    def get_user_info(self, user_id) -> Dict:
        pass

    def get_team_info(self) -> Dict:
        pass

def print_exception(ex):
    print("*** An exception occurred:", ex)
    traceback.print_exc()
    tb = traceback.extract_tb(ex.__traceback__)  # Extract the traceback
    for filename, lineno, name, line in tb:
        print(f"File: {filename}, Line: {lineno}, Function: {name}, Code: {line}")
    return



def _mattermost_team_info(team_id):
    if team_id not in teams_cache:
        try:
            response_team = mattermost_client.teams.get_team(team_id)
            teams_cache[team_id] = response_team['team']
        except Exception as ex:
            print_exception(ex)
            return
            

def _preload(team_id):
    pass
    #_mattermost_team_info(team_id)


async def handler(event_raw):
    try:
        global mattermost_client, logger
        event = json.loads(event_raw)
        print(event)

        event_type = event.get('event')
        print('>>>', event_type)
        if event_type in (None, 'hello', 'typing', 'post_deleted', 'post', 'status_change'):
            logger.debug(f"Found message of subtype {event.get('subtype')}")
            return
        
        event_post = json.loads(event['data']['post'])

        channel_id = event_post.get('channel_id')
        team_id = event['data'].get('team_id')
        user_id = event_post.get('user_id')
        post_id = event_post.get('id')

        
        message_raw = event_post['message']
        print(event_type, message_raw)

        _preload(team_id)

        timestamp = datetime.datetime.fromtimestamp(float(event_post['create_at']) / 1000.0)
        permalink_raw = mattermost_client.posts.get_post(post_id) #. web_client.chat_getPermalink(channel=channel_id, message_ts=event['ts'])
        # permalink = permalink_raw['permalink']
        permalink = ""

        # https://mm.r-europe.eu/reddit-reurope/pl/yaa4fue16bdhzpdhz1fzqqu4yh

        conversation = MattermostConversation(bot_name, channel_id, user_id, team_id)
        message: Message = Message(conversation, timestamp, permalink, message_raw)
        if message_raw == "eurobot test":
            data = {
                "Apple Employees": [
                    {"Name": "Steve Wozniak", "Role": "Co-founder and Engineer", "Start Year": 1976},
                    {"Name": "Steve Jobs", "Role": "Co-founder and Visionary", "Start Year": 1976},
                    {"Name": "Mike Markkula", "Role": "Investor and Consultant", "Start Year": 1977},
                    {"Name": "Bill Fernandez", "Role": "Early Engineer", "Start Year": 1977},
                ],
                "Planets": [
                    {"Name": "Mercury", "Diameter (km)": 4880, "Distance from Sun (million km)": 57.9, "Moons": 0},
                    {"Name": "Venus", "Diameter (km)": 12104, "Distance from Sun (million km)": 108.2, "Moons": 0},
                    {"Name": "Earth", "Diameter (km)": 12742, "Distance from Sun (million km)": 149.6, "Moons": 1},
                    {"Name": "Mars", "Diameter (km)": 6779, "Distance from Sun (million km)": 227.9, "Moons": 2},
                    {"Name": "Jupiter", "Diameter (km)": 139820, "Distance from Sun (million km)": 778.5, "Moons": 79},
                    {"Name": "Saturn", "Diameter (km)": 116460, "Distance from Sun (million km)": 1429, "Moons": 83},
                    {"Name": "Uranus", "Diameter (km)": 50724, "Distance from Sun (million km)": 2871, "Moons": 27},
                    {"Name": "Neptune", "Diameter (km)": 49244, "Distance from Sun (million km)": 4495, "Moons": 14},
                ],
            }
            # conversation.send_tables("Sample Tables", data)
            conversation.send_table("Planets", data['Planets'])
        else:
            handle_message(message)

        # print(message)
    except Exception as ex:
        print("*** An exception occurred:", ex)
        tb = traceback.extract_tb(ex.__traceback__)  # Extract the traceback
        for filename, lineno, name, line in tb:
            print(f"File: {filename}, Line: {lineno}, Function: {name}, Code: {line}")
        return

def chat_connect(a_bot_name, a_line_handler):
    global bot_name, line_handler, logger, mattermost_client
    bot_name = a_bot_name
    line_handler = a_line_handler
    mattermost_client = Driver({
        'url': os.environ['MATTERMOST_API_URL'],
        'scheme': 'http',
        'token': os.environ['MATTERMOST_API_TOKEN']
    })
    mattermost_client.login()
    # print(mattermost_client.users.get_user_by_username('gschizas'))
    mattermost_client.init_websocket(handler)


def tests():
    # Replace these with your actual bot user credentials and details
    BASE_URL = "https://mm.r-europe.eu"
    BOT_TOKEN = os.environ['MATTERMOST_API_TOKEN']
    MESSAGE_TEXT = "Hello from my bot!"

    # Function to send a message as the bot
    def send_message(base_url, bot_token, channel_id, message_text):
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "channel_id": channel_id,
            "message": message_text
        }

        url = f"{base_url}/api/v4/posts"

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            print("Message sent successfully!")
        else:
            print(f"Failed to send message: {response.status_code} {response.reason}\n{response.text}")

    def get_channels(base_url, bot_token, team_id):
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }
        
        # url = f"{base_url}/api/v4/teams/{team_id}/channels"
        url = f"{base_url}/api/v4/users/me/teams"
        print(url)
        
        response = requests.get(url, headers=headers)
        
    def get_channels(base_url, bot_token, team_id):
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{base_url}/api/v4/teams/{team_id}/channels"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            channels = response.json()
            print(response.text)
            for channel in channels:
                # Check channel type
                channel_type = "Public" if channel["type"] == "O" else "Private" if channel["type"] == "P" else "Direct/Group"
                print(f"Channel Name: {channel['name']} | Channel ID: {channel['id']} | Type: {channel_type}")
        else:
            print(f"Failed to fetch channels: {response.status_code} {response.reason}")

        url = f"{base_url}/api/v4/teams/{team_id}/channels/private"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            channels = response.json()
            print(response.text)
            for channel in channels:
                # Check channel type
                channel_type = "Public" if channel["type"] == "O" else "Private" if channel["type"] == "P" else "Direct/Group"
                print(f"Channel Name: {channel['name']} | Channel ID: {channel['id']} | Type: {channel_type}")
        else:
            print(f"Failed to fetch channels: {response.status_code} {response.reason}")


    def get_teams(base_url, bot_token):
        headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{base_url}/api/v4/users/me/teams"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            teams = response.json()
            for team in teams:
                print(f"Team Name: {team['name']} | Team ID: {team['id']}")
        else:
            print(f"Failed to fetch teams: {response.status_code} {response.reason}")



    # 
    get_teams(BASE_URL, BOT_TOKEN)
    team_id = 'miejdgzti7fm9ju4nyasim8dfe'
    get_channels(BASE_URL, BOT_TOKEN, team_id)
    channel_id = 'weohbqfg1t83urnxsrgkjo4i4a'
    channel_id = '53okohka67femr77g5s1f3hw7a'
    send_message(BASE_URL, BOT_TOKEN, channel_id, "Hello from eurobot (not working yet)")


