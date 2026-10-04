# Copyright (c) 2026 yuu61

"""Resolve validated connection settings from supplied inventory values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from air_ssh.domain.credentials import resolve_enable_password, resolve_password
from air_ssh.domain.errors import UsageError
from air_ssh.domain.inventory import entry_text

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_SSH_PORT = 65535
DEFAULT_SSH_PORT = 22

# "wlc": AireOS WLC / Mobility Express controller CLI ("me" is accepted as an alias).
# "ap": a Wave 2 / Catalyst Wi-Fi 6 AP's own CLI (user EXEC ">" then privileged EXEC "#").
KINDS = {"wlc": "wlc", "me": "wlc", "ap": "ap"}


@dataclass(frozen=True)
class Target:
    """A resolved device connection, with credentials omitted from its repr."""

    name: str
    host: str
    username: str
    password: str = field(repr=False)
    port: int = DEFAULT_SSH_PORT
    kind: str = "wlc"
    enable_password: str | None = field(default=None, repr=False)
    port_explicit: bool = field(default=False, kw_only=True)

    @property
    def is_ap(self) -> bool:
        """Whether this target uses the AP's own privileged CLI."""
        return self.kind == "ap"


def resolve_kind(entry: Mapping[str, object], name: str) -> str:
    """Normalize the inventory's controller or AP kind.

    Returns:
        The session kind, accepting me as an alias for wlc.

    Raises:
        UsageError: The supplied kind is unsupported.

    """
    raw = entry_text(entry, "kind") or "wlc"
    kind = KINDS.get(raw.strip().lower())
    if kind is None:
        message = f"unknown kind {raw!r} for {name!r}; use wlc, me, or ap"
        raise UsageError(message)
    return kind


def resolve_target(name: str, entry: Mapping[str, object], env: Mapping[str, str]) -> Target:
    """Validate connection fields and resolve the device's credentials.

    Returns:
        A target ready for the infrastructure layer to connect.

    Raises:
        UsageError: The host, username, or SSH port is invalid.

    """
    host = entry_text(entry, "host", "hostname", "address", "ip")
    username = entry_text(entry, "username", "user")
    if not host or not host.strip():
        message = f"no host for {name!r}; add host to devices.json"
        raise UsageError(message)
    if not username or not username.strip():
        message = f"no username for {name!r}; add username to devices.json"
        raise UsageError(message)
    port = entry.get("port", DEFAULT_SSH_PORT)
    if isinstance(port, str) and port.isascii() and port.isdecimal():
        port = int(port)
    if type(port) is not int or not 1 <= port <= MAX_SSH_PORT:
        message = f"invalid SSH port for {name!r}; expected 1..65535"
        raise UsageError(message)
    kind = resolve_kind(entry, name)
    password = resolve_password(entry, env)
    enable = resolve_enable_password(entry, env, password) if kind == "ap" else None
    return Target(name, host, username, password, port, kind, enable, port_explicit="port" in entry)
