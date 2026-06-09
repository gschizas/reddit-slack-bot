"""Account record passed to provider provision/deprovision stubs."""
from dataclasses import dataclass


@dataclass
class Account:
    name: str
    email: str
