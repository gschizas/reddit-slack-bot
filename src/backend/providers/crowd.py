"""Atlassian Crowd directory provisioning (STUB).

Real integration target: Crowd REST API
    POST   /rest/usermanagement/1/user        (create user)
    DELETE /rest/usermanagement/1/user        (remove user)
"""
from backend.providers.base import Account


def provision(ctx, account: Account) -> str:
    # TODO: create the user in Crowd via the Crowd REST API.
    ctx.logger.info(f"[stub] Create Crowd entry for {account.email}")
    return f"Crowd entry would be created for {account.name} <{account.email}> (stub)"


def deprovision(ctx, account: Account) -> str:
    # TODO: remove the user from Crowd via the Crowd REST API.
    ctx.logger.info(f"[stub] Remove Crowd entry for {account.email}")
    return f"Crowd entry would be removed for {account.name} <{account.email}> (stub)"
