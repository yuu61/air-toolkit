# Copyright (c) 2026 yuu61

"""Inventory and SSH adapters used by the application layer."""

from air_ssh.infrastructure.inventory import read_inventory
from air_ssh.infrastructure.session import open_session

__all__ = ["open_session", "read_inventory"]
