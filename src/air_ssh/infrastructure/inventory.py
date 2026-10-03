# Copyright (c) 2026 yuu61

"""Locate and decode the agent-independent inventory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from air_ssh.domain import UsageError, parse_inventory

if TYPE_CHECKING:
    from collections.abc import Mapping


def inventory_path(override: str | None, env: Mapping[str, str]) -> Path:
    """Locate the inventory using the override, supplied environment, or home.

    Returns:
        The expanded inventory path.

    """
    chosen = override or env.get("AIR_TOOLKIT_INVENTORY")
    return Path(chosen).expanduser() if chosen else Path.home() / ".air-toolkit" / "devices.json"


def read_inventory(
    override: str | None = None, env: Mapping[str, str] | None = None
) -> tuple[dict[str, dict[str, object]], Path]:
    """Read and validate an inventory, accepting a UTF-8 byte order mark.

    Returns:
        The device entries and path, with an empty inventory for a missing default.

    Raises:
        UsageError: An explicit file is missing or the file cannot be decoded.

    """
    env = os.environ if env is None else env
    path = inventory_path(override, env)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        # A first --list should explain where to create the inventory.
        if not override and not env.get("AIR_TOOLKIT_INVENTORY"):
            return {}, path
        message = f"inventory file not found: {path}"
        raise UsageError(message) from None
    except json.JSONDecodeError as exc:
        message = f"invalid JSON in {path} at line {exc.lineno}, column {exc.colno}"
        raise UsageError(message) from None
    except (OSError, UnicodeError):
        # Do not include file contents or a decoder's offending bytes (passwords).
        message = f"cannot read inventory: {path}"
        raise UsageError(message) from None
    return parse_inventory(data, str(path)), path
