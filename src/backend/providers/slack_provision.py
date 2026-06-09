"""Slack account deactivation (STUB).

Real integration target: Slack SCIM API
    DELETE /scim/v2/Users/{id}    (deactivate a member)
Requires an org/workspace admin token with the ``admin`` SCIM scope.
"""
from backend.providers.base import Account


def deactivate(ctx, account: Account) -> str:
    # TODO: deactivate the Slack member via the SCIM Users endpoint.
    ctx.logger.info(f"[stub] Deactivate Slack user {account.email}")
    return f"Slack account would be deactivated for {account.email} (stub)"
