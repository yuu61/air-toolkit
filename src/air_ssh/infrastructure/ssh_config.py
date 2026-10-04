# Copyright (c) 2026 yuu61

"""Resolve OpenSSH aliases and validate every host before opening a jump route."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from air_ssh.domain import Target, UsageError
from air_ssh.domain.target import DEFAULT_SSH_PORT, MAX_SSH_PORT

if TYPE_CHECKING:
    from collections.abc import Mapping

CONFIG_TIMEOUT = 10
MAX_JUMPS = 32


@dataclass(frozen=True)
class SshHost:
    """A jump's alias and the user/port selected by OpenSSH."""

    alias: str
    host: str
    user: str
    port: int

    @property
    def jump_spec(self) -> str:
        """A ProxyJump argument retaining the alias's other SSH settings."""
        alias = f"[{self.alias}]" if ":" in self.alias else self.alias
        return f"{self.user}@{alias}:{self.port}"


@dataclass(frozen=True)
class SshRoute:
    """The final address and an already validated sequence of jump hosts."""

    host: str
    port: int
    jumps: tuple[SshHost, ...] = ()
    executable: str | None = None
    config_file: Path | None = None


def _uri_address(value: str) -> tuple[str, str | None, int | None]:
    try:
        address = urlsplit(value)
        host, user, port = address.hostname, address.username, address.port
    except ValueError:
        message = "invalid ProxyJump address in SSH config"
        raise UsageError(message) from None
    if (
        not host
        or any((address.password is not None, address.path, address.query, address.fragment))
        or (port is not None and not 1 <= port <= MAX_SSH_PORT)
    ):
        message = "invalid ProxyJump address in SSH config"
        raise UsageError(message)
    return host, unquote(user) if user else None, port


def _jump_address(value: str) -> tuple[str, str | None, int | None]:
    # ssh -G normalizes the last SSH URI and may bracket IPv4, but leaves URIs
    # for earlier hosts in a comma-separated list unchanged.
    if value.startswith("ssh://"):
        return _uri_address(value)
    user, separator, address = value.rpartition("@")
    user = user if separator else None
    match = re.fullmatch(r"(?:\[([^\]]+)\]|([^:\[\]]+))(?::([0-9]+))?", address)
    if match is None:
        message = "invalid ProxyJump address in SSH config"
        raise UsageError(message)
    host = match[1] or match[2]
    try:
        port = int(match[3]) if match[3] else None
    except ValueError:
        message = "invalid ProxyJump address in SSH config"
        raise UsageError(message) from None
    if port is not None and not 1 <= port <= MAX_SSH_PORT:
        message = "invalid ProxyJump address in SSH config"
        raise UsageError(message)
    return host, user, port


def _lookup(
    executable: str,
    config_file: Path,
    alias: str,
    user: str | None = None,
    port: int | None = None,
) -> dict[str, str]:
    command = [executable, "-G", "-F", str(config_file)]
    if user is not None:
        command.extend(["-l", user])
    if port is not None:
        command.extend(["-p", str(port)])
    command.extend(["--", alias])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CONFIG_TIMEOUT,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        message = f"cannot resolve SSH config for {alias!r}"
        raise UsageError(message) from None
    if result.returncode:
        # OpenSSH's diagnostics can include arbitrary config lines; do not echo them.
        message = f"invalid SSH config for {alias!r} ({config_file})"
        raise UsageError(message)
    settings = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(" ")
        if separator:
            settings.setdefault(key.lower(), value.strip())
    if settings.get("proxycommand", "none").lower() != "none":
        message = f"ProxyCommand is not supported for {alias!r}; use ProxyJump"
        raise UsageError(message)
    return settings


def _endpoint(alias: str, settings: Mapping[str, str]) -> SshHost:
    try:
        port = int(settings["port"])
        host, user = settings["hostname"], settings["user"]
    except (KeyError, ValueError):
        message = f"incomplete SSH config for {alias!r}"
        raise UsageError(message) from None
    if not host or not user or not 1 <= port <= MAX_SSH_PORT:
        message = f"invalid SSH destination for {alias!r}"
        raise UsageError(message)
    return SshHost(alias, host, user, port)


def _jumps(
    executable: str,
    config_file: Path,
    settings: Mapping[str, str],
    ancestors: frozenset[tuple[str, str, int]],
) -> tuple[SshHost, ...]:
    value = settings.get("proxyjump", "none")
    if value.lower() == "none":
        return ()
    result: list[SshHost] = []
    for index, spec in enumerate(value.split(",")):
        alias, user, port = _jump_address(spec)
        resolved = _lookup(executable, config_file, alias, user, port)
        jump = _endpoint(alias, resolved)
        identity = (jump.host, jump.user, jump.port)
        if identity in ancestors or len(ancestors) + len(result) > MAX_JUMPS:
            message = "ProxyJump route is cyclic or exceeds 32 jump hosts"
            raise UsageError(message)
        # OpenSSH's explicit a,b list overrides b's ProxyJump with a. Only the
        # first listed jump inherits its own route from the configuration file.
        if index == 0:
            result.extend(_jumps(executable, config_file, resolved, ancestors | {identity}))
        result.append(jump)
    if len(result) > MAX_JUMPS:
        message = "ProxyJump route exceeds 32 jump hosts"
        raise UsageError(message)
    return tuple(result)


def resolve_route(target: Target) -> SshRoute:
    """Read ~/.ssh/config, resolve aliases, and reject effective ProxyCommands.

    Returns:
        A direct route when the user has no config, otherwise the resolved route.

    Raises:
        UsageError: OpenSSH/config is unavailable, or the route is unsupported.

    """
    config_file = Path.home() / ".ssh" / "config"
    try:
        config_file.stat()
    except FileNotFoundError:
        return SshRoute(target.host, target.port)
    except OSError:
        message = f"cannot read SSH config: {config_file}"
        raise UsageError(message) from None
    executable = shutil.which("ssh")
    if executable is None:
        message = "OpenSSH ssh is required to read ~/.ssh/config; add ssh to PATH"
        raise UsageError(message)
    port = target.port if target.port_explicit or target.port != DEFAULT_SSH_PORT else None
    settings = _lookup(executable, config_file, target.host, target.username, port)
    final = _endpoint(target.host, settings)
    jumps = _jumps(
        executable, config_file, settings, frozenset({(final.host, final.user, final.port)})
    )
    return SshRoute(final.host, final.port, jumps, executable, config_file)
