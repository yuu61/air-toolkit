# Copyright (c) 2026 yuu61

"""One invocation: select the target, execute operations, restore WLANs, close."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TextIO

from air_ssh import infrastructure
from air_ssh.domain import (
    Command,
    CycleWlan,
    OperationError,
    Target,
    UsageError,
    entry_text,
    resolve_kind,
    resolve_target,
    select_entry,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


@dataclass(frozen=True)
class Request:
    """An ordered operation batch and its device selection and output flags."""

    operations: tuple[Command | CycleWlan, ...] = ()
    device: str | None = None
    inventory: str | None = None
    save: bool = False
    list_devices: bool = False


class Session(Protocol):
    """The device operations required by a batch, independent of SSH transport."""

    def run(self, command: str) -> bool:
        """Execute a command and report whether it completed."""
        ...

    def wlan_enabled(self, wlan_id: str) -> bool:
        """Read a controller WLAN's current enabled state."""
        ...

    def save(self) -> None:
        """Persist the controller configuration and verify completion."""
        ...

    def close(self) -> None:
        """Disconnect without sending commands into an unfinished exchange."""
        ...


def restore_wlan(session: Session, cycle: CycleWlan, *, was_enabled: bool) -> None:
    """Restore and verify a WLAN's state before advancing or saving.

    Raises:
        OperationError: Restoration timed out or the original state was not recovered.

    """
    if session.wlan_enabled(cycle.wlan_id) != was_enabled:
        command = cycle.enable if was_enabled else cycle.disable
        if not session.run(command):
            message = f"WLAN {cycle.wlan_id} restoration timed out"
            raise OperationError(message)
        if session.wlan_enabled(cycle.wlan_id) != was_enabled:
            message = f"WLAN {cycle.wlan_id} did not return to its original state"
            raise OperationError(message)


def _disable_wlan(session: Session, cycle: CycleWlan) -> None:
    if not session.run(cycle.disable):
        message = "WLAN disable timed out; stopping the cycle"
        raise OperationError(message)
    if session.wlan_enabled(cycle.wlan_id):
        message = "WLAN is still enabled; stopping the cycle"
        raise OperationError(message)


def execute(req: Request, session: Session, err: TextIO) -> None:
    """Execute commands in order, restoring active WLANs even after a failure.

    Raises:
        OperationError: A command timed out or WLAN cleanup failed, preventing saving.

    """
    active: tuple[CycleWlan, bool] | None = None
    failed = False
    try:
        for operation in req.operations:
            if isinstance(operation, CycleWlan):
                if active is not None:
                    restore_wlan(session, active[0], was_enabled=active[1])
                    active = None
                was_enabled = session.wlan_enabled(operation.wlan_id)
                # Register before sending: a failed read may follow a successful disable.
                active = (operation, was_enabled)
                if was_enabled:
                    _disable_wlan(session, operation)
            elif not session.run(operation.text):
                message = "command timed out; stopping the batch without saving"
                raise OperationError(message)
    finally:
        if active is not None:
            try:
                restore_wlan(session, active[0], was_enabled=active[1])
            except Exception as exc:
                failed = True
                print(f"[ERROR] cleanup WLAN {active[0].wlan_id} failed: {exc}", file=err)
    if failed:
        message = "one or more commands failed; configuration was not saved"
        raise OperationError(message)
    # Persist the restored WLAN state, rather than the temporary disabled state.
    if req.save:
        session.save()


def run(
    req: Request,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    open_session: Callable[[Target, TextIO, TextIO], Session] = infrastructure.open_session,
) -> None:
    """Resolve the request and run its session, or list the inventory without SSH.

    Raises:
        UsageError: The request is empty or uses controller-only operations on an AP.

    """
    env = os.environ if env is None else env
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if not req.list_devices and not req.operations and not req.save:
        message = "no commands provided (give commands, --save, or --list)"
        raise UsageError(message)
    devices, path = infrastructure.read_inventory(req.inventory, env)
    if req.list_devices:
        print(f"Inventory: {path}", file=out)
        for name, entry in devices.items():
            host = entry_text(entry, "host", "hostname", "address", "ip") or "(no host)"
            user = entry_text(entry, "username", "user") or "(no username)"
            try:
                kind = resolve_kind(entry, name)
            except UsageError:
                # --list shows no inventory values beyond host and user; connecting
                # reports the bad kind in full.
                kind = "(unknown kind)"
            print(f"{name}\t{host}\t{user}\t{kind}", file=out)
        if not devices:
            print("No devices. Add devices to the inventory shown above.", file=out)
        return
    name, entry = select_entry(req.device, devices, env)
    target = resolve_target(name, entry, env)
    if target.is_ap:
        # WLAN cycles and save config exist on the controller CLI only.
        if any(isinstance(operation, CycleWlan) for operation in req.operations):
            message = f"--cycle-wlan applies to controllers; {name!r} is an AP"
            raise UsageError(message)
        if req.save:
            message = f"--save applies to controllers; {name!r} is an AP"
            raise UsageError(message)
    session = open_session(target, out, err)
    try:
        execute(req, session, err)
    finally:
        try:
            session.close()
        except Exception as exc:
            # Netmiko's paging reset can fail on an already-busy channel.
            print(f"[WARN] disconnect failed: {exc}", file=err)
