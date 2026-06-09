"""Onboard / offboard commands.

Both are gated behind the generic approval queue (see ``backend.approval``): issuing
them enqueues a request that a designated approver must approve before the actual
provisioning runs. Provisioning itself is delegated to the provider stubs in
``backend.providers``.
"""
import os
from typing import List

import click

from backend.approval import requires_approval
from backend.providers import PROVIDERS, RESOURCE_LABELS, Account, slack_provision
from commands import gyrobot
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')

_RESOURCE_FLAGS = list(PROVIDERS.keys())


def _selected_resources(params: dict) -> List[str]:
    return [key for key in _RESOURCE_FLAGS if params.get(key)]


def _onboard_summary(params: dict) -> str:
    resources = ', '.join(RESOURCE_LABELS[key] for key in _selected_resources(params))
    return f"onboard {params['name']} <{params['email']}> [{resources}]"


def _onboard_validate(params: dict):
    if not _selected_resources(params):
        return ("Select at least one resource to provision: "
                + ', '.join(f'--{key}' for key in _RESOURCE_FLAGS))


def _offboard_summary(params: dict) -> str:
    return f"offboard {params['name']} <{params['email']}> (all resources + Slack)"


@gyrobot.command('onboard')
@click.argument('name')
@click.argument('email')
@click.option('--github', is_flag=True, help='Provision a GitHub Copilot licence')
@click.option('--jetbrains', is_flag=True, help='Provision a JetBrains IntelliJ IDEA licence')
@click.option('--crowd', is_flag=True, help='Provision a Crowd entry')
@click.pass_context
@requires_approval(summarize=_onboard_summary, validate=_onboard_validate)
def onboard(ctx: ExtendedContext, name: str, email: str,
            github: bool, jetbrains: bool, crowd: bool):
    """Onboard a new colleague (queued for approval)"""
    account = Account(name=name, email=email)
    selected = _selected_resources({'github': github, 'jetbrains': jetbrains, 'crowd': crowd})
    results = []
    for key in selected:
        message = PROVIDERS[key].provision(ctx, account)
        results.append({'Resource': RESOURCE_LABELS[key], 'Result': message})
    ctx.chat.send_table(title=f'Onboarded {name}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)


@gyrobot.command('offboard')
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_offboard_summary)
def offboard(ctx: ExtendedContext, name: str, email: str):
    """Offboard a colleague: remove all licences/entries and deactivate Slack (queued for approval)"""
    account = Account(name=name, email=email)
    results = []
    for key, provider in PROVIDERS.items():
        message = provider.deprovision(ctx, account)
        results.append({'Resource': RESOURCE_LABELS[key], 'Result': message})
    results.append({'Resource': 'Slack account', 'Result': slack_provision.deactivate(ctx, account)})
    ctx.chat.send_table(title=f'Offboarded {name}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)
