# Copyright (c) 2026 yuu61

"""Device credentials take precedence over the legacy global WLC_PASS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from air_ssh.domain.errors import UsageError
from air_ssh.domain.inventory import entry_text

if TYPE_CHECKING:
    from collections.abc import Mapping


def resolve_password(entry: Mapping[str, object], env: Mapping[str, str]) -> str:
    """Resolve the login password from the device entry and supplied environment.

    Returns:
        The first available device, device-environment, or legacy WLC password.

    Raises:
        UsageError: No password is available.

    """
    password = entry_text(entry, "password")
    if password:
        return password
    variable = entry_text(entry, "password_env")
    if variable and env.get(variable):
        return env[variable]
    if env.get("WLC_PASS"):
        return env["WLC_PASS"]
    message = 'no password available; add "password" or "password_env" to devices.json'
    raise UsageError(message)


def resolve_enable_password(
    entry: Mapping[str, object], env: Mapping[str, str], password: str
) -> str:
    """Resolve the AP's privileged EXEC secret.

    Returns:
        The configured enable secret, falling back to the login password.

    """
    secret = entry_text(entry, "enable_password", "enable_secret")
    if secret:
        return secret
    variable = entry_text(entry, "enable_password_env")
    if variable and env.get(variable):
        return env[variable]
    return password
