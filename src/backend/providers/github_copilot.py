"""GitHub Copilot licence provisioning (STUB).

Real integration target: GitHub Copilot seat management API
    POST/DELETE /orgs/{org}/copilot/billing/selected_users
See backend/github_sdk.py for an authenticated requests.Session pattern.
"""
from backend.providers.base import Account


def provision(ctx, account: Account) -> str:
    # TODO: assign a Copilot seat via the GitHub Copilot billing API.
    ctx.logger.info(f"[stub] Assign GitHub Copilot licence to {account.email}")
    return f"GitHub Copilot licence would be assigned to {account.email} (stub)"


def deprovision(ctx, account: Account) -> str:
    # TODO: remove the Copilot seat via the GitHub Copilot billing API.
    ctx.logger.info(f"[stub] Remove GitHub Copilot licence from {account.email}")
    return f"GitHub Copilot licence would be removed from {account.email} (stub)"
