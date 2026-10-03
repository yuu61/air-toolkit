# Copyright (c) 2026 yuu61

"""Inventory structure and device selection. No filesystem access."""

from __future__ import annotations

from collections.abc import Mapping

from air_ssh.domain.errors import UsageError


def parse_inventory(data: object, where: str) -> dict[str, dict[str, object]]:
    """Validate a bare or wrapped inventory without exposing entry values.

    Returns:
        Named device entries, excluding names reserved for comments.

    Raises:
        UsageError: The inventory structure or a device name is invalid.

    """
    devices = data.get("devices", data) if isinstance(data, Mapping) else None
    if not isinstance(devices, Mapping):
        message = f'{where}: expected {{"devices": {{name: {{...}}}}}}'
        raise UsageError(message)
    result = {}
    for name, entry in devices.items():
        if not isinstance(name, str) or not name:
            message = f"{where}: device names must be non-empty strings"
            raise UsageError(message)
        if name.startswith("_"):
            continue
        if not isinstance(entry, Mapping):
            message = f"{where}: device {name!r} must be an object"
            raise UsageError(message)
        result[name] = dict(entry)
    return result


def entry_text(entry: Mapping[str, object], *keys: str) -> str | None:
    """Read the first non-empty string among a field's accepted aliases.

    Returns:
        The field value, or None if all aliases are absent or empty.

    Raises:
        UsageError: A supplied field is not a string.

    """
    for key in keys:
        value = entry.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            message = f"inventory field {key!r} must be a string"
            raise UsageError(message)
        if value:
            return value
    return None


def select_entry(
    device: str | None, devices: Mapping[str, Mapping[str, object]], env: Mapping[str, str]
) -> tuple[str, Mapping[str, object]]:
    """Select an explicitly named device, preferring the CLI over the environment.

    Returns:
        The selected device's name and inventory entry.

    Raises:
        UsageError: No device was selected or the name is unknown.

    """
    name = device or env.get("AIR_TOOLKIT_DEVICE")
    if not name:
        message = "select a device with --device NAME or $AIR_TOOLKIT_DEVICE (see --list)"
        raise UsageError(message)
    if name not in devices:
        message = f"unknown device {name!r} (see --list)"
        raise UsageError(message)
    return name, devices[name]
