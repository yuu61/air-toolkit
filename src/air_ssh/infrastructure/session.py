# Copyright (c) 2026 yuu61

"""Netmiko transport and AireOS's streaming/prompt protocol."""

from __future__ import annotations

import re
import sys
import time
from contextlib import ExitStack
from typing import TYPE_CHECKING, TextIO

from air_ssh.domain import OperationError, Target, UsageError
from air_ssh.infrastructure.jump import JumpTunnel
from air_ssh.infrastructure.ssh_config import resolve_route

if TYPE_CHECKING:
    from netmiko import BaseConnection

# A waiting question ends its line with (y/n); the controller may put a warning
# sentence before it on the same line ("Clear ap-config will ... reboot the AP.
# Are you sure you want continue? (y/n)"). Dotted leaders mark show output, never
# a question, so a line containing them is never answered.
CONFIRM_RE = re.compile(
    r"(?![^\r\n]*\.{3,})[^\r\n]*?"
    r"(?:Are you sure\b|Would you like\b|Do you (?:want|wish)\b|Proceed\b|Please confirm\b)"
    r"[^\r\n]*\(y/n\)\s*[:?]?",
    re.IGNORECASE,
)
SAVE_CONFIRM_RE = re.compile(r"Are you sure you want to save\?\s*\(y/n\)\s*[:?]?", re.IGNORECASE)
ENTER_RE = re.compile(
    r"Press (?:Enter|any key) to continue(?:\s+Or <Ctl Z> to abort)?\.*", re.IGNORECASE
)
MORE_RE = re.compile(r"--More--(?:\s+or \(q\)uit)?", re.IGNORECASE)
PROMPT_RE = re.compile(r"\([^\r\n]+\)\s*>")
ERROR_RE = re.compile(
    r"^\s*(?:%\s*)?(?:Request failed\b|Error(?:\s*:|!|$)|"
    r"Invalid (?:command|input|parameter|argument|WLAN)\b|"
    r"Incorrect usage\b|Usage\s*:|Command (?:failed|not found)\b|"
    r"Unable to\b|Permission denied\b|Not authorized\b)",
    re.IGNORECASE | re.MULTILINE,
)
# A documented refusal of a config command ("Cannot change Exp Bw Req mode while
# 802.11a network is operational."). Only config commands are judged by it, so a
# show dump that happens to start a line with the word cannot fail a status read.
CONFIG_ERROR_RE = re.compile(r"^\s*Cannot\b", re.IGNORECASE | re.MULTILINE)
# A Wave 2 / Catalyst Wi-Fi 6 AP: user EXEC "hostname>" or privileged EXEC "hostname#",
# and the CLI error messages the AP command reference documents.
AP_PROMPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[>#]")
AP_ERROR_RE = re.compile(
    r"^\s*%\s*(?:Ambiguous command\b|Incomplete command\b|Invalid input\b)",
    re.IGNORECASE | re.MULTILINE,
)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DEFAULT_TIMEOUT = 120
# How long the escape key may take to bring the root prompt back after an abandoned command.
RECOVERY_TIMEOUT = 10
# q exits MORE output; Ctrl-Z returns to the root prompt from any mode and aborts
# a "Press Enter to continue Or <Ctl Z> to abort" pause.
QUIT_MORE = "q"
CTRL_Z = "\x1a"


def waiting_line(tail: str) -> str:
    """Strip terminal controls and extract the controller's last printed line.

    Returns:
        The complete waiting line as a human would see it.

    """
    clean_tail = ANSI_RE.sub("", tail).replace("\r", "\n").rstrip()
    return clean_tail.rsplit("\n", 1)[-1].strip()


class NetmikoSession:
    """AireOS WLC / Mobility Express controller CLI."""

    DEVICE = "controller"
    # What follows Netmiko's base prompt, and the fallback when there is none.
    PROMPT_TAIL = r"\s*>"
    FALLBACK_PROMPT = PROMPT_RE

    def __init__(
        self,
        conn: BaseConnection,
        out: TextIO,
        err: TextIO,
        *,
        resources: ExitStack | None = None,
    ) -> None:
        """Bind the connection, output streams, and device-specific root prompt."""
        self._conn = conn
        self._out = out
        self._err = err
        self._ready = True
        self._resources = resources if resources is not None else ExitStack()
        base_prompt = getattr(conn, "base_prompt", None)
        self._prompt = (
            re.compile(re.escape(base_prompt.strip()) + self.PROMPT_TAIL)
            if isinstance(base_prompt, str) and base_prompt.strip()
            else self.FALLBACK_PROMPT
        )

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
        """Stream a command using an inactivity timeout rather than total runtime.

        Returns:
            Whether the exchange completed before the inactivity timeout.

        """
        return self._exchange(command, timeout) is not None

    def _rejected(self, command: str, output: str) -> bool:
        is_config = command.split(maxsplit=1)[0].lower() == "config"
        return bool(ERROR_RE.search(output) or (is_config and CONFIG_ERROR_RE.search(output)))

    def _answer(self, command: str, line: str) -> str | None:
        """Choose a reply only for a recognized, complete waiting line.

        Returns:
            The reply to send, or None to keep waiting.

        """
        if ENTER_RE.fullmatch(line):
            return "\n"
        if MORE_RE.fullmatch(line):
            return " "
        confirm = SAVE_CONFIRM_RE if command.strip().lower() == "save config" else CONFIRM_RE
        if confirm.fullmatch(line):
            return "y\n"
        return None

    def _exchange(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> str | None:
        if not self._ready:
            message = "SSH command state is unknown; reconnect before further commands"
            raise OperationError(message)
        print(f"===== {command} =====", file=self._out)
        self._ready = False
        self._conn.write_channel(command + "\n")
        tail = ""
        chunks = []
        prompt_pending = False
        last_data = time.monotonic()
        while True:
            chunk = self._conn.read_channel()
            if chunk:
                print(chunk, end="", flush=True, file=self._out)
                chunks.append(chunk)
                tail = (tail + chunk)[-4096:]
                last_data = time.monotonic()
                prompt_pending = False
                continue
            # Only answer a complete waiting line, never a substring in normal output
            # or a command echo. A quiet read lets fragmented lines finish first.
            line = waiting_line(tail)
            response = None if line == command.strip() else self._answer(command, line)
            if response is not None:
                self._conn.write_channel(response)
                tail = ""
                prompt_pending = False
            elif self._prompt.fullmatch(line):
                # The prompt also precedes command echo: wait for two quiet reads.
                if prompt_pending:
                    self._ready = True
                    print(file=self._out)
                    output = ANSI_RE.sub("", "".join(chunks)).replace("\r", "\n")
                    # A bare command echo must not be mistaken for an error response.
                    output = "\n".join(
                        row for row in output.splitlines() if row.strip() != command.strip()
                    )
                    if self._rejected(command, output):
                        message = f"{self.DEVICE} rejected '{command}'"
                        raise OperationError(message)
                    return output
                prompt_pending = True
            elif time.monotonic() - last_data > timeout:
                print(f"\n[WARN] no output for {timeout}s on '{command}'", file=self._err)
                self._recover(command, line)
                return None
            time.sleep(0.3)

    def _recover(self, command: str, line: str) -> None:
        """Abandon the pending command and try to get the root prompt back.

        A MORE pause that MORE_RE did not recognize (debug output can be appended
        to it) is left with q; anything else with Ctrl-Z. Regaining the prompt lets
        a WLAN disabled earlier in the batch be restored. The abandoned command
        stays a failure either way.
        """
        self._conn.write_channel(QUIT_MORE if "--more--" in line.lower() else CTRL_Z)
        tail = ""
        prompt_pending = False
        last_data = time.monotonic()
        while True:
            chunk = self._conn.read_channel()
            if chunk:
                print(chunk, end="", flush=True, file=self._out)
                tail = (tail + chunk)[-4096:]
                last_data = time.monotonic()
                prompt_pending = False
                continue
            if self._prompt.fullmatch(waiting_line(tail)):
                if prompt_pending:
                    self._ready = True
                    print(file=self._out)
                    print(f"[WARN] prompt recovered; '{command}' was abandoned", file=self._err)
                    return
                prompt_pending = True
            elif time.monotonic() - last_data > RECOVERY_TIMEOUT:
                print(
                    "[WARN] prompt not recovered; reconnect before further commands", file=self._err
                )
                return
            time.sleep(0.3)

    def save(self) -> None:
        """Save the controller configuration and require its success marker.

        Raises:
            OperationError: The save did not finish with confirmation.

        """
        output = self._exchange("save config")
        if output is None or not re.search(
            r"^\s*Configuration Saved!\s*$", output, re.MULTILINE | re.IGNORECASE
        ):
            message = "configuration save was not confirmed"
            raise OperationError(message)

    def wlan_enabled(self, wlan_id: str) -> bool:
        """Read the requested WLAN and require an unambiguous identifier and status.

        Returns:
            Whether the requested WLAN is enabled.

        Raises:
            OperationError: The WLAN identifier or status could not be confirmed.

        """
        output = self._exchange(f"show wlan {wlan_id}")
        if output is not None:
            identifiers = re.findall(r"^WLAN Identifier\.*\s+(\d+)\s*$", output, re.MULTILINE)
            states = re.findall(
                r"^Status\.*\s+(Enabled|Disabled)\s*$", output, re.MULTILINE | re.IGNORECASE
            )
            if identifiers == [wlan_id] and len(states) == 1:
                return states[0].lower() == "enabled"
        message = f"could not determine status of WLAN {wlan_id}"
        raise OperationError(message)

    def close(self) -> None:
        """Close the transport first so Netmiko does not run slow paging/logout cleanup."""
        try:
            if hasattr(self._conn, "paramiko_cleanup"):
                self._conn.paramiko_cleanup()
            self._conn.disconnect()
        finally:
            self._resources.close()


class ApSession(NetmikoSession):
    """A Wave 2 / Catalyst Wi-Fi 6 AP's own CLI, in privileged EXEC.

    Netmiko's IOS handling has already set "terminal length 0", so nothing pauses,
    and the AP command reference documents no questions to answer: an unexpected
    prompt is left to the inactivity timeout and Ctrl-Z. WLAN cycles and
    "save config" belong to the controller CLI and are refused.
    """

    DEVICE = "AP"
    PROMPT_TAIL = r"[>#]"
    FALLBACK_PROMPT = AP_PROMPT_RE

    def _rejected(self, command: str, output: str) -> bool:
        return AP_ERROR_RE.search(output) is not None

    def _answer(self, command: str, line: str) -> str | None:
        return None

    def save(self) -> None:
        """Reject controller configuration saving on the AP CLI.

        Raises:
            UsageError: AP sessions do not support save config.

        """
        message = "--save applies to controllers; the AP CLI has no save config"
        raise UsageError(message)

    def wlan_enabled(self, wlan_id: str) -> bool:
        """Reject controller WLAN operations on the AP CLI.

        Raises:
            UsageError: AP sessions do not expose controller WLANs.

        """
        message = "--cycle-wlan applies to controllers; the AP CLI has no WLANs"
        raise UsageError(message)


def open_session(target: Target, out: TextIO, err: TextIO) -> NetmikoSession:
    """Connect and prepare a controller or privileged AP session.

    Returns:
        The ready session, with terminal length 0 or AP enable mode configured.

    Raises:
        UsageError: Netmiko is unavailable in the current interpreter.
        OperationError: The SSH connection failed.

    """
    # Help and inventory listing do not require Netmiko.
    try:
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
        from paramiko.ssh_exception import SSHException
    except ImportError:
        message = f"netmiko is not installed for {sys.executable}; run uv sync"
        raise UsageError(message) from None
    route = resolve_route(target)
    options = {
        "host": route.host,
        "port": route.port,
        "username": target.username,
        "password": target.password,
        "fast_cli": False,
    }
    if target.is_ap:
        options |= {"device_type": "cisco_ios", "secret": target.enable_password}
    else:
        options["device_type"] = "cisco_wlc_ssh"
    with ExitStack() as resources:
        if route.jumps:
            tunnel = JumpTunnel(route)
            resources.callback(tunnel.close)
            options["sock"] = tunnel.sock
        try:
            conn = ConnectHandler(**options)
        except (
            NetmikoAuthenticationException,
            NetmikoTimeoutException,
            SSHException,
            OSError,
            EOFError,
        ) as exc:
            message = f"SSH connection to {target.name!r} failed ({type(exc).__name__})"
            if route.jumps:
                message += "; check ProxyJump authentication and known_hosts"
            raise OperationError(message) from None
        session_type = ApSession if target.is_ap else NetmikoSession
        session = session_type(conn, out, err, resources=resources.pop_all())
        try:
            if target.is_ap:
                _enter_privileged_exec(conn, target, NetmikoTimeoutException)
        except BaseException:
            try:
                session.close()
            except Exception as exc:
                print(f"[WARN] disconnect after initialization failure failed: {exc}", file=err)
            raise
        return session


def _enter_privileged_exec(
    conn: BaseConnection, target: Target, timeout_error: type[Exception]
) -> None:
    # The AP starts in user EXEC (">"); "enable" asks for the secret. Netmiko reports
    # a wrong or missing secret as ValueError, which must not leak past the CLI.
    try:
        conn.enable()
    except (ValueError, timeout_error, OSError):
        message = f"could not enter privileged EXEC on {target.name!r}; check enable_password"
        raise OperationError(message) from None
