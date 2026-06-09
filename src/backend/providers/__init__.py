"""Provisioning providers for onboarding/offboarding.

Each resource provider exposes ``provision(ctx, account)`` and
``deprovision(ctx, account)`` returning a human-readable status string. The
implementations here are stubs that log the intended action and return a message;
the real API integrations belong where the ``# TODO`` markers are.
"""
from backend.providers.base import Account
from backend.providers import crowd, github_copilot, jetbrains, slack_provision

# Resource key -> provider module (must expose provision/deprovision).
PROVIDERS = {
    'github': github_copilot,
    'jetbrains': jetbrains,
    'crowd': crowd,
}

# Human-readable labels for each resource key.
RESOURCE_LABELS = {
    'github': 'GitHub Copilot licence',
    'jetbrains': 'JetBrains IntelliJ IDEA licence',
    'crowd': 'Crowd entry',
}

__all__ = ['Account', 'PROVIDERS', 'RESOURCE_LABELS', 'slack_provision']
