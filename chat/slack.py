class SlackWrapper:
    def __init__(self, bot_name):
        self.bot_name = bot_name
        self.users = {}
        self.teams = {}
        self.channels = {}
        self.web_client = None
        self.team_id = None
        self.channel_id = None
        self.user_id = None
        self.message = None
        self.permalink = None

    def load(self, web_client, team_id, channel_id, user_id, msg, permalink):
        self.web_client = web_client
        self.team_id = team_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.message = msg
        self.permalink = permalink

    def preload(self, user_id, team_id, channel_id):
        self.slack_team_info(team_id)
        self.slack_user_info(user_id)
        self.slack_channel_info(team_id, channel_id)

    def send_text(self, text, is_error=False, icon_emoji=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        self.web_client.chat_postMessage(
            channel=self.channel_id,
            text=text,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_ephemeral(self, text=None, blocks=None, is_error=False, icon_emoji=None):
        if icon_emoji is None:
            icon_emoji = ':robot_face:' if not is_error else ':face_palm:'
        self.web_client.chat_postEphemeral(
            channel=self.channel_id,
            blocks=blocks,
            text=text,
            user=self.user_id,
            icon_emoji=icon_emoji,
            username=self.bot_name)

    def send_file(self, file_data, title=None, filename=None, filetype=None):
        self.web_client.files_upload(
            channels=self.channel_id,
            icon_emoji=':robot_face:',
            username=self.bot_name,
            file=file_data,
            filename=filename,
            title=title,
            filetype=filetype or 'auto')

    def send_fields(self, text, fields):
        self.web_client.chat_postMessage(
            channel=self.channel_id,
            icon_emoji=':robot_face:',
            text=text,
            username=self.bot_name,
            attachments=fields)

    def send_blocks(self, blocks):
        self.web_client.chat_postMessage(
            channel=self.channel_id,
            icon_emoji=':robot_face:',
            blocks=blocks,
            username=self.bot_name)

    def slack_user_info(self, user_id):
        if user_id not in self.users:
            response_user = self.web_client.users_info(user=user_id)
            if response_user['ok']:
                self.users[user_id] = response_user['user']

    def slack_team_info(self, team_id):
        if team_id not in self.teams:
            response_team = self.web_client.team_info()
            if response_team['ok']:
                self.teams[team_id] = response_team['team']

    def slack_channel_info(self, team_id, channel_id):
        if team_id not in self.channels:
            self.channels[team_id] = {}
        if channel_id not in self.channels[team_id]:
            response_channel = self.web_client.conversations_info(channel=channel_id)
            channel_info = response_channel['channel'] if response_channel['ok'] else {}
            if channel_info.get('is_group') or channel_info.get('is_channel'):
                priv = '🔒' if channel_info.get('is_private') else '#'
                self.channels[team_id][channel_id] = priv + channel_info['name_normalized']
            elif channel_info.get('is_im'):
                response_members = self.web_client.conversations_members(channel=channel_id)
                for user_id in response_members['members']:
                    self.slack_user_info(user_id)
                participants = [f"{self.users[user_id]['real_name']} <{self.users[user_id]['name']}@{user_id}>"
                                for user_id in response_members['members']]
                self.channels[team_id][channel_id] = '🧑' + ' '.join(participants)
