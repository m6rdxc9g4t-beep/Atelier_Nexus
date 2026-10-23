"""Extension factice pour tests/test_plugins.py."""

CALLS: list[str] = []


def register() -> None:
    CALLS.append("register")
