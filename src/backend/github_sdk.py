import os

import requests

ses: requests.Session | None = None


def _init_session():
    global ses
    if ses is not None:
        return
    token = os.environ['GITHUB_TOKEN']
    ses = requests.Session()
    ses.headers.update({
        'Accept': 'application/vnd.github+json',
        "Authorization": f"Bearer {token}",
        'X-GitHub-Api-Version': '2022-11-28'
    })


def get_org_members(org):
    _init_session()

    url = f"https://api.github.com/orgs/{org}/members"
    members = []
    page = 1

    while True:
        response = ses.get(url, params={"per_page": 100, "page": page})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch members: {response.status_code} {response.text}")
        data = response.json()
        if not data:
            break
        members.extend(data)
        page += 1

    return members


def get_org_teams(org):
    _init_session()

    url = f"https://api.github.com/orgs/{org}/teams"
    teams = []
    page = 1

    while True:
        response = ses.get(url, params={"per_page": 100, "page": page})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch members: {response.status_code} {response.text}")
        data = response.json()
        if not data:
            break
        teams.extend(data)
        page += 1

    return teams


def get_org_team_members(org, team_slug):
    _init_session()

    url = f"https://api.github.com/orgs/{org}/teams/{team_slug}/members"
    team_members = []
    page = 1

    while True:
        response = ses.get(url, params={"per_page": 100, "page": page})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch members: {response.status_code} {response.text}")
        data = response.json()
        if not data:
            break
        team_members.extend(data)
        page += 1

    return team_members


def get_user_details(username):
    pass


def get_sso_identity(org_name, username):
    _init_session()

    url = f"https://api.github.com/orgs/{org_name}/memberships/{username}"
    response = ses.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("user", {}).get("login"), data.get("user", {}).get("sso", {}).get("login")
    return username, None
