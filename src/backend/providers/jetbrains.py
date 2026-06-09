"""JetBrains IntelliJ IDEA licence provisioning (STUB).

Real integration target: JetBrains Account / Licenses API for organizations
    https://account.jetbrains.com/ (assign/revoke a subscription seat).
"""
from backend.providers.base import Account


def provision(ctx, account: Account) -> str:
    # TODO: assign a JetBrains IntelliJ IDEA licence seat via the JetBrains API.
    ctx.logger.info(f"[stub] Assign JetBrains IntelliJ IDEA licence to {account.email}")
    return f"JetBrains IntelliJ IDEA licence would be assigned to {account.email} (stub)"


def deprovision(ctx, account: Account) -> str:
    # TODO: revoke the JetBrains IntelliJ IDEA licence seat via the JetBrains API.
    ctx.logger.info(f"[stub] Remove JetBrains IntelliJ IDEA licence from {account.email}")
    return f"JetBrains IntelliJ IDEA licence would be removed from {account.email} (stub)"
