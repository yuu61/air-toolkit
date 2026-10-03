# Copyright (c) 2026 yuu61

"""Errors the application can report directly to the CLI user."""


class UsageError(Exception):
    """An invalid request or inventory, suitable for display by the CLI."""


class OperationError(Exception):
    """An SSH operation could not be completed."""
