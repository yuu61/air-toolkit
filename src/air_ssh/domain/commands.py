# Copyright (c) 2026 yuu61

"""Ordered commands and WLAN cycles, independent of SSH and argument parsing."""

from __future__ import annotations

from dataclasses import dataclass

from air_ssh.domain.errors import UsageError

MAX_WLAN_ID = 512
MAX_WLAN_ID_DIGITS = len(str(MAX_WLAN_ID))

# Root-level words that open a sub-mode prompt on their own instead of running
# anything. air-ssh only recognizes the root prompt, so such a token would wait
# for the inactivity timeout.
MODE_WORDS = frozenset({"clear", "config", "debug", "reset", "save", "show", "transfer"})
# Commands that end the CLI session; air-ssh disconnects by itself.
SESSION_WORDS = frozenset({"exit", "logout"})


@dataclass(frozen=True)
class Command:
    """A single command that preserves the session's root prompt."""

    text: str

    def __post_init__(self) -> None:
        """Reject empty, multiline, mode-changing, or session-ending commands.

        Raises:
            UsageError: The command cannot be executed safely in this session.

        """
        if not self.text.strip() or any(c in self.text for c in "\r\n\x00"):
            message = "commands must be non-empty single lines"
            raise UsageError(message)
        words = self.text.lower().split()
        shown = self.text.strip()
        if len(words) == 1 and words[0] in MODE_WORDS:
            message = f"'{shown}' alone only opens a sub-mode prompt; give the complete command"
            raise UsageError(message)
        if words[0] in SESSION_WORDS:
            message = f"'{shown}' ends the session; air-ssh disconnects by itself"
            raise UsageError(message)
        if words[:2] == ["config", "prompt"]:
            message = (
                "config prompt changes the prompt air-ssh waits for; run it from another session"
            )
            raise UsageError(message)
        if "?" in shown and not shown.endswith("?"):
            message = f"'{shown}' contains '?' mid-command; '?' is only supported at the end"
            raise UsageError(message)
        if shown.count("?") > 1:
            message = f"'{shown}' contains multiple '?'; give a single '?' at the end"
            raise UsageError(message)

    @property
    def is_help(self) -> bool:
        """Whether this command queries interactive help or completions with trailing '?'."""
        return self.text.strip().endswith("?")


@dataclass(frozen=True)
class CycleWlan:
    """A WLAN whose original state must be restored after its command group."""

    wlan_id: str

    def __post_init__(self) -> None:
        """Validate and normalize the controller's ASCII WLAN identifier.

        Raises:
            UsageError: The identifier is outside the supported range.

        """
        normalized = self.wlan_id.lstrip("0")
        if (
            not normalized.isascii()
            or not normalized.isdecimal()
            or len(normalized) > MAX_WLAN_ID_DIGITS
            or not 1 <= int(normalized) <= MAX_WLAN_ID
        ):
            message = "--cycle-wlan requires a WLAN id in 1..512"
            raise UsageError(message)
        object.__setattr__(self, "wlan_id", normalized)

    @property
    def disable(self) -> str:
        """The controller command that disables this WLAN."""
        return f"config wlan disable {self.wlan_id}"

    @property
    def enable(self) -> str:
        """The controller command that enables this WLAN."""
        return f"config wlan enable {self.wlan_id}"
