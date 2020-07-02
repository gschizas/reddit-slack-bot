import base64
import os

from bot_framework.yaml_wrapper import yaml
from flask import Flask, request, abort, make_response
import requests


app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = base64.b64decode(os.environ['SLACK_SECRET_KEY'])

user_cache = {}

with open('data/protected_channels.yml') as f:
    protected_channels = yaml.load(f)


@app.route('/')
def index():
    return ""


@app.route('/auth')
def auth():
    print(request.data)
    pass


@app.route('/event', methods=('GET', 'POST'))
def event():
    if not request.json:
        abort(400)

    call_type = request.json['type']
    if call_type == 'url_verification':
        challenge = request.json['challenge']
        return challenge
    elif call_type == 'event_callback':
        the_event = request.json['event']
        event_type = the_event['type']
        if event_type == 'member_joined_channel':
            the_team = the_event['team']
            the_channel = the_event['channel']
            the_user = the_event['user']
            if the_team in protected_channels and the_channel in protected_channels[the_team] and the_user not in protected_channels[the_team][the_channel]:
                token = os.environ['SLACK_API_TOKEN']
                resp = requests.post(
                    'https://slack.com/api/conversations.kick',
                    json={
                        'channel': the_channel,
                        'user': the_user},
                    headers={
                        'Content-type': 'application/json',
                        'Authorization': 'Bearer ' + token})
                assert resp.ok
                return make_response('', 200)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
