import base64
import collections
import datetime
import json
import os
import pathlib
import re
import urllib.parse
import zlib

import click
import praw
import requests
import unicodedata
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from treelib import Node, Tree

from bot_framework.yaml_wrapper import yaml
from commands import gyrobot, DefaultCommandGroup, ClickAliasedGroup
from commands.extended_context import ExtendedContext
from commands.github.github_sdk import get_org_teams

if 'GITHUB_TOKEN' not in os.environ:
    raise ImportError('GITHUB_TOKEN not found in environment')

if 'GITHUB_ORG' not in os.environ:
    raise ImportError('GITHUB_ORG not found in environment')


@gyrobot.group('github', cls=DefaultCommandGroup)
def github():
    pass


@github.command('teams')
@click.pass_context
def github_teams(ctx):
    """Display GitHub Teams"""
    def generate_tree(node_name, parent_node=None):
        parent = tree.create_node(node_name, node_name.lower(), parent=parent_node)
        for branch_name in sorted(connections.get(node_name, []), key=lambda x: x.lower()):
            generate_tree(branch_name, parent)

    teams = get_org_teams(os.environ['GITHUB_ORG'])

    import json
    with open('/tmp/eurobot-test.json', 'w') as f:
        json.dump(teams, f)

    connections = {
        'GitHub': [t['slug'] for t in teams if t.get('parent') is None]
    }

    for team in connections['GitHub']:
        child_teams = [t['slug'] for t in teams
                       if t.get('parent') is not None
                       and t.get('parent', {'name': ''})['name'] == team]
        if child_teams:
            connections[team] = child_teams

    tree = Tree()
    generate_tree('GitHub')
    text = tree.show(key=lambda x: x.identifier, line_type='ascii-ex', stdout=False)

    ctx.chat.send_text('```\n' + text + '```\n')
