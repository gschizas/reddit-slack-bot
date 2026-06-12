"""Onboard / offboard commands.

Both are gated behind the generic approval queue (see ``backend.approval``): issuing
them enqueues a request that a designated approver must approve before the actual
provisioning runs. Provisioning itself is delegated to the provider stubs in
``backend.providers``.
"""
import os

import click

from backend.approval import requires_approval
from backend.providers import PROVIDERS, RESOURCE_LABELS, Account, slack_provision
from commands import gyrobot
from commands.extended_context import ExtendedContext

if 'APPROVAL_DATABASE_URL' not in os.environ:
    raise ImportError('APPROVAL_DATABASE_URL not found in environment')


def _github_summary(params: dict) -> str:
    return f"onboard {params['name']} <{params['email']}> [GitHub Copilot]"


def _jetbrains_summary(params: dict) -> str:
    return f"onboard {params['name']} <{params['email']}> [JetBrains]"


def _crowd_summary(params: dict) -> str:
    return f"onboard {params['name']} <{params['email']}> [Crowd]"


def _slack_summary(params: dict) -> str:
    return f"onboard {params['name']} <{params['email']}> [Slack]"


def _offboard_summary(params: dict) -> str:
    return f"offboard {params['name']} <{params['email']}> (all resources + Slack)"


@gyrobot.group('onboard')
@click.pass_context
def onboard(ctx: ExtendedContext):
    """Onboard a colleague for specific resources (queued for approval)"""
    ctx.ensure_object(dict)


@onboard.command('github')
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_github_summary)
def onboard_github(ctx: ExtendedContext, name: str, email: str):
    """Onboard a colleague for GitHub Copilot"""
    account = Account(name=name, email=email)
    message = PROVIDERS['github'].provision(ctx, account)
    result = [{'Resource': RESOURCE_LABELS['github'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {name}', table=result)
    return f"{RESOURCE_LABELS['github']}: {message}"


@onboard.command('jetbrains')
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_jetbrains_summary)
def onboard_jetbrains(ctx: ExtendedContext, name: str, email: str):
    """Onboard a colleague for JetBrains IntelliJ IDEA"""
    account = Account(name=name, email=email)
    message = PROVIDERS['jetbrains'].provision(ctx, account)
    result = [{'Resource': RESOURCE_LABELS['jetbrains'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {name}', table=result)
    return f"{RESOURCE_LABELS['jetbrains']}: {message}"


@onboard.command('crowd')
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_crowd_summary)
def onboard_crowd(ctx: ExtendedContext, name: str, email: str):
    """Onboard a colleague for Crowd entry"""
    account = Account(name=name, email=email)
    message = PROVIDERS['crowd'].provision(ctx, account)
    result = [{'Resource': RESOURCE_LABELS['crowd'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {name}', table=result)
    return f"{RESOURCE_LABELS['crowd']}: {message}"


@onboard.command("slack")
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_slack_summary)
def onboard_slack(ctx: ExtendedContext, name: str, email: str):
    """Onboard a colleague for Slack entry"""
    account = Account(name=name, email=email)
    message = PROVIDERS['slack'].provision(ctx, account)
    result = [{'Resource': RESOURCE_LABELS['slack'], 'Result': message}]
    ctx.chat.send_table(title=f'Onboarded {name}', table=result)
    return f"{RESOURCE_LABELS['slack']}: {message}"


@gyrobot.command('offboard')
@click.argument('name')
@click.argument('email')
@click.pass_context
@requires_approval(summarize=_offboard_summary)
def offboard(ctx: ExtendedContext, name: str, email: str):
    """Offboard a colleague: remove all licenses/entries and deactivate Slack (queued for approval)"""
    account = Account(name=name, email=email)
    results = []
    for key, provider in PROVIDERS.items():
        message = provider.deprovision(ctx, account)
        results.append({'Resource': RESOURCE_LABELS[key], 'Result': message})
    results.append({'Resource': 'Slack account', 'Result': slack_provision.deactivate(ctx, account)})
    ctx.chat.send_table(title=f'Offboarded {name}', table=results)
    return '\n'.join(f"{row['Resource']}: {row['Result']}" for row in results)
