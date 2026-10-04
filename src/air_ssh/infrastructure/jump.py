# Copyright (c) 2026 yuu61

"""Bridge native OpenSSH forwarding to a socket on both Windows and POSIX."""

from __future__ import annotations

import socket
import subprocess
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import TYPE_CHECKING

from air_ssh.domain import OperationError

if TYPE_CHECKING:
    from air_ssh.infrastructure.ssh_config import SshRoute

BUFFER_SIZE = 65536
CLOSE_TIMEOUT = 2


class JumpTunnel:
    """Own an ssh -W process and its duplex socket bridge."""

    def __init__(self, route: SshRoute) -> None:
        """Start the validated jump route using the user's native OpenSSH client.

        Raises:
            OperationError: The forwarding process could not be started.

        """
        last = route.jumps[-1]
        self._config_directory = TemporaryDirectory(prefix="air-ssh-")
        config_file = Path(self._config_directory.name) / "config"
        # -J propagates -F, but does not propagate -o BatchMode=yes. Put it ahead
        # of the user's config so every nested ssh remains non-interactive.
        original = str(route.config_file).replace("\\", "/").replace('"', '\\"')
        try:
            config_file.write_text(
                f'Host *\n    BatchMode yes\nInclude "{original}"\n', encoding="utf-8"
            )
            self.sock, self._bridge = socket.socketpair()
        except OSError:
            self._config_directory.cleanup()
            message = "could not prepare OpenSSH for ProxyJump"
            raise OperationError(message) from None
        command = [
            str(route.executable),
            "-F",
            str(config_file),
            "-o",
            "BatchMode=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-T",
            "-W",
            f"[{route.host}]:{route.port}",
            "-l",
            last.user,
            "-p",
            str(last.port),
        ]
        if len(route.jumps) > 1:
            command.extend(["-J", ",".join(jump.jump_spec for jump in route.jumps[:-1])])
        command.extend(["--", last.alias])
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError:
            self.sock.close()
            self._bridge.close()
            self._config_directory.cleanup()
            message = "could not start OpenSSH for ProxyJump"
            raise OperationError(message) from None
        self._threads = [
            Thread(target=self._send, daemon=True),
            Thread(target=self._receive, daemon=True),
        ]
        try:
            for thread in self._threads:
                thread.start()
        except BaseException:
            self.close()
            raise

    def _send(self) -> None:
        stream = self._process.stdin
        if stream is None:
            return
        try:
            while data := self._bridge.recv(BUFFER_SIZE):
                stream.write(data)
                stream.flush()
        except (OSError, ValueError):
            pass
        finally:
            with suppress(OSError, ValueError):
                stream.close()

    def _receive(self) -> None:
        stream = self._process.stdout
        if stream is None:
            return
        try:
            while data := stream.read1(BUFFER_SIZE):
                self._bridge.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            with suppress(OSError):
                self._bridge.shutdown(socket.SHUT_WR)

    def close(self) -> None:
        """Stop forwarding and release sockets, processes, pipes, and workers."""
        try:
            self._stop()
        finally:
            self._config_directory.cleanup()

    def _stop(self) -> None:
        for sock in (self.sock, self._bridge):
            with suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        if self._process.poll() is None:
            self._process.terminate()
        try:
            self._process.wait(timeout=CLOSE_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=CLOSE_TIMEOUT)
        for thread in self._threads:
            if thread.ident is not None:
                thread.join(timeout=CLOSE_TIMEOUT)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()
