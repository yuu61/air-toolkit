# Copyright (c) 2026 yuu61

"""Verify alias resolution, preflight rejection, and forwarding without SSH connections."""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import shutil
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING
from unittest.mock import Mock, call, patch

from air_ssh.cli import main
from air_ssh.domain import OperationError, Target, UsageError, resolve_target
from air_ssh.infrastructure import jump, ssh_config
from air_ssh.infrastructure.jump import JumpTunnel
from air_ssh.infrastructure.session import ApSession, open_session
from air_ssh.infrastructure.ssh_config import SshHost, SshRoute, resolve_route

if TYPE_CHECKING:
    from collections.abc import Sequence

SSH = shutil.which("ssh")
TRANSFER_TIMEOUT = 10
ECHO_PROCESS = (
    "import sys\nwhile data := sys.stdin.buffer.read1(65536):\n"
    " sys.stdout.buffer.write(data)\n sys.stdout.buffer.flush()\n"
)


def _private_config(path: Path) -> None:
    # Windows OpenSSH rejects TEMP's inherited OWNER RIGHTS ACL on Includes.
    # Restrict only this temporary fixture, never the user's real SSH files.
    if sys.platform == "win32":
        ssh_config.subprocess.run(
            [
                shutil.which("icacls"),
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{getpass.getuser()}:F",
            ],
            capture_output=True,
            check=True,
            timeout=TRANSFER_TIMEOUT,
            shell=False,
        )
    else:
        path.chmod(0o600)


class ConfigTests(unittest.TestCase):
    """Use temporary user configs; ssh -G never opens an SSH connection."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="air ssh config ")
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.config = self.home / ".ssh" / "config"
        patcher = patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_config(self, text: str) -> None:
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text(text, encoding="utf-8")

    def test_missing_config_does_not_require_openssh(self) -> None:
        with patch("air_ssh.infrastructure.ssh_config.shutil.which", return_value=None):
            self.assertEqual(
                resolve_route(Target("lab", "192.0.2.1", "operator", "test-secret", 2222)),
                SshRoute("192.0.2.1", 2222),
            )

    def test_config_requires_openssh_and_does_not_fall_back_to_direct(self) -> None:
        self.write_config("Host lab\n HostName 192.0.2.1\n")
        with (
            patch("air_ssh.infrastructure.ssh_config.shutil.which", return_value=None),
            self.assertRaisesRegex(UsageError, "OpenSSH"),
        ):
            resolve_route(Target("lab", "lab", "operator", "test-secret"))

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_alias_include_wildcard_and_port_precedence(self) -> None:
        self.write_config(
            f'Include "{(self.config.parent / "hosts").as_posix()}"\n'
            "Host lab-*\n Port 2222\n User config-user\n"
        )
        included = self.config.parent / "hosts"
        included.write_text("Host lab-wlc\n HostName 192.0.2.1\n", encoding="utf-8")
        _private_config(included)
        for entry, port in (({}, 2222), ({"port": 22}, 22), ({"port": "2200"}, 2200)):
            with self.subTest(entry=entry):
                target = resolve_target(
                    "wlc",
                    {"host": "lab-wlc", "username": "admin", "password": "test-secret", **entry},
                    {},
                )
                route = resolve_route(target)
                self.assertEqual((route.host, route.port, route.jumps), ("192.0.2.1", port, ()))

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_nested_jump_aliases_and_explicit_chain(self) -> None:
        self.write_config(
            "Host lab\n HostName 192.0.2.1\n ProxyJump inner\n"
            "Host inner\n HostName 192.0.2.2\n User inner-user\n Port 2202\n ProxyJump outer\n"
            "Host outer\n HostName 192.0.2.3\n User outer-user\n Port 2203\n"
        )
        target = Target("lab", "lab", "operator", "test-secret")
        route = resolve_route(target)
        self.assertEqual(
            route.jumps,
            (
                SshHost("outer", "192.0.2.3", "outer-user", 2203),
                SshHost("inner", "192.0.2.2", "inner-user", 2202),
            ),
        )
        self.write_config(
            "Host lab\n HostName 192.0.2.1\n ProxyJump outer,override@inner:2222\n"
            "Host outer\n HostName 192.0.2.3\n User outer-user\n"
            "Host inner\n HostName 192.0.2.2\n User unused-user\n ProxyJump unused\n"
            "Host unused\n ProxyCommand this-must-never-run\n"
        )
        route = resolve_route(target)
        self.assertEqual([host.alias for host in route.jumps], ["outer", "inner"])
        self.assertEqual((route.jumps[-1].user, route.jumps[-1].port), ("override", 2222))

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_uri_and_ipv6_jump_addresses(self) -> None:
        self.write_config(
            "Host lab\n HostName 2001:db8::1\n ProxyJump jump-user@[2001:db8::2]:2200\n"
        )
        route = resolve_route(Target("lab", "lab", "operator", "test-secret"))
        self.assertEqual(route.host, "2001:db8::1")
        self.assertEqual(route.jumps[0], SshHost("2001:db8::2", "2001:db8::2", "jump-user", 2200))
        self.assertEqual(route.jumps[0].jump_spec, "jump-user@[2001:db8::2]:2200")
        self.write_config("Host lab\n ProxyJump ssh://jump-user@192.0.2.2:2200\n")
        route = resolve_route(Target("lab", "lab", "operator", "test-secret"))
        self.assertEqual(route.jumps[0], SshHost("192.0.2.2", "192.0.2.2", "jump-user", 2200))
        self.write_config("Host lab\n ProxyJump ssh://jump-user@192.0.2.2:2200,last\n")
        route = resolve_route(Target("lab", "lab", "operator", "test-secret"))
        self.assertEqual(route.jumps[0], SshHost("192.0.2.2", "192.0.2.2", "jump-user", 2200))
        self.assertEqual(route.jumps[1].alias, "last")

    def test_jump_limit_accepts_32_and_rejects_33(self) -> None:
        self.write_config("Host lab\n")
        for count in (32, 33):
            with self.subTest(count=count):

                def resolved(
                    command: Sequence[str], *, jump_count: int = count, **_kwargs: object
                ) -> Mock:
                    alias = command[-1]
                    output = f"hostname {alias}\nuser admin\nport 22\n"
                    if alias == "lab":
                        output += (
                            "proxyjump "
                            + ",".join(f"jump{number}" for number in range(jump_count))
                            + "\n"
                        )
                    return Mock(returncode=0, stdout=output)

                with (
                    patch("air_ssh.infrastructure.ssh_config.shutil.which", return_value="ssh"),
                    patch("air_ssh.infrastructure.ssh_config.subprocess.run", side_effect=resolved),
                ):
                    target = Target("lab", "lab", "admin", "test-secret")
                    if count == ssh_config.MAX_JUMPS:
                        self.assertEqual(len(resolve_route(target).jumps), count)
                    else:
                        with self.assertRaisesRegex(UsageError, "32 jump hosts"):
                            resolve_route(target)

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_proxycommand_on_final_or_later_jump_fails_before_any_connection(self) -> None:
        for config in (
            "Host lab\n ProxyCommand test-secret must-never-run\n",
            (
                "Host lab\n ProxyJump first,second\nHost first\n ProxyJump outer\n"
                "Host outer\n ProxyCommand test-secret must-never-run\n"
            ),
            (
                "Host lab\n ProxyJump first,second\nHost second\n"
                " ProxyCommand test-secret must-never-run\n"
            ),
        ):
            with self.subTest(config=config):
                self.write_config(config)
                with (
                    patch("netmiko.ConnectHandler") as connect,
                    patch("air_ssh.infrastructure.session.JumpTunnel") as tunnel,
                    self.assertRaisesRegex(UsageError, "ProxyCommand") as raised,
                ):
                    open_session(
                        Target("lab", "lab", "operator", "test-secret"),
                        io.StringIO(),
                        io.StringIO(),
                    )
                self.assertNotIn("test-secret", str(raised.exception))
                connect.assert_not_called()
                tunnel.assert_not_called()

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_none_is_a_disabled_proxy(self) -> None:
        for setting in ("ProxyCommand none", "ProxyJump none"):
            with self.subTest(setting=setting):
                self.write_config(f"Host lab\n HostName 192.0.2.1\n {setting}\n")
                self.assertFalse(resolve_route(Target("lab", "lab", "admin", "test-secret")).jumps)

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_cycle_is_rejected_without_connecting(self) -> None:
        for config in (
            "Host lab\n ProxyJump lab\n",
            (
                "Host lab\n ProxyJump first\nHost first\n ProxyJump second\n"
                "Host second\n ProxyJump first\n"
            ),
            "Host lab\n ProxyJump other\nHost lab other\n HostName 192.0.2.1\n User admin\n",
        ):
            with self.subTest(config=config):
                self.write_config(config)
                with self.assertRaisesRegex(UsageError, "cyclic|invalid SSH config"):
                    resolve_route(Target("lab", "lab", "admin", "test-secret"))

    def test_lookup_failure_and_timeout_do_not_expose_config_text(self) -> None:
        self.write_config("Host lab\n")
        for outcome in (
            Mock(returncode=255, stdout="", stderr="test-secret"),
            ssh_config.subprocess.TimeoutExpired(["ssh"], 10, stderr="test-secret"),
            OSError("test-secret"),
            Mock(returncode=0, stdout="host lab\nport broken\n", stderr=""),
        ):
            with self.subTest(outcome=outcome):
                with (
                    patch("air_ssh.infrastructure.ssh_config.shutil.which", return_value="ssh"),
                    patch("air_ssh.infrastructure.ssh_config.subprocess.run") as run,
                    self.assertRaises(UsageError) as raised,
                ):
                    if isinstance(outcome, BaseException):
                        run.side_effect = outcome
                    else:
                        run.return_value = outcome
                    resolve_route(Target("lab", "lab", "admin", "test-secret"))
                self.assertNotIn("test-secret", str(raised.exception))

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_cli_proxycommand_exits_one_without_connecting(self) -> None:
        self.write_config("Host lab\n ProxyCommand must-never-run\n")
        inventory = self.home / "devices.json"
        inventory.write_text(
            json.dumps({"lab": {"host": "lab", "username": "admin", "password": "test-secret"}}),
            encoding="utf-8",
        )
        with patch("netmiko.ConnectHandler") as connect, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(
                main(["--inventory", str(inventory), "--device", "lab", "show sysinfo"]), 1
            )
        self.assertIn("ProxyCommand", err.getvalue())
        connect.assert_not_called()


class TunnelTests(unittest.TestCase):
    """Exercise native config inheritance and local forwarding process lifetimes."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="air ssh forwarding ")
        self.addCleanup(directory.cleanup)
        self.config_file = Path(directory.name) / "config with spaces"
        self.first_key = Path(directory.name) / "first identity key"
        self.last_key = Path(directory.name) / "last identity key"
        self.config_file.write_text(
            "Host first\n HostName 192.0.2.1\n User first-user\n Port 2201\n"
            f' IdentityFile "{self.first_key.as_posix()}"\n IdentitiesOnly yes\n BatchMode no\n'
            "Host last\n HostName 192.0.2.2\n User last-user\n Port 2202\n"
            f' IdentityFile "{self.last_key.as_posix()}"\n IdentitiesOnly yes\n BatchMode no\n',
            encoding="utf-8",
        )
        _private_config(self.config_file)
        self.processes = []
        self.threads = []
        self.sockets = []
        self.commands = []

    def route(self) -> SshRoute:
        return SshRoute(
            "2001:db8::1",
            2222,
            (
                SshHost("first", "192.0.2.1", "first-user", 2201),
                SshHost("last", "192.0.2.2", "last-user", 2202),
            ),
            "ssh",
            self.config_file,
        )

    def start_tunnel(self, script: str = ECHO_PROCESS) -> JumpTunnel:
        real_popen = jump.subprocess.Popen
        real_socketpair = socket.socketpair

        def child(command: Sequence[str], **kwargs: object) -> object:
            self.assertFalse(kwargs["shell"])
            self.commands.append(command)
            process = real_popen([sys.executable, "-u", "-c", script], **kwargs)
            self.processes.append(process)
            self.addCleanup(self.stop_child, process)
            return process

        def worker(**kwargs: object) -> Thread:
            thread = Thread(**kwargs)
            self.threads.append(thread)
            return thread

        def sockets() -> tuple[socket.socket, socket.socket]:
            pair = real_socketpair()
            self.sockets.extend(pair)
            return pair

        with (
            patch("air_ssh.infrastructure.jump.subprocess.Popen", side_effect=child),
            patch("air_ssh.infrastructure.jump.Thread", side_effect=worker),
            patch("air_ssh.infrastructure.jump.socket.socketpair", side_effect=sockets),
        ):
            tunnel = JumpTunnel(self.route())
        self.addCleanup(tunnel.close)
        tunnel.sock.settimeout(TRANSFER_TIMEOUT)
        return tunnel

    @staticmethod
    def stop_child(process: object) -> None:
        # A broken close implementation must not leave test children running.
        if process.poll() is None:
            process.kill()
        process.wait(timeout=TRANSFER_TIMEOUT)

    @staticmethod
    def receive_to_eof(sock: socket.socket) -> bytes:
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
        return b"".join(chunks)

    def assert_closed(self) -> None:
        self.assertTrue(all(sock.fileno() == -1 for sock in self.sockets))
        self.assertTrue(all(not thread.is_alive() for thread in self.threads))
        for process in self.processes:
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
        for command in self.commands:
            config = Path(command[command.index("-F") + 1])
            self.assertFalse(config.parent.exists())

    def test_binary_socket_bridge_and_process_cleanup(self) -> None:
        tunnel = self.start_tunnel()
        payload = b"SSH-2.0-test\r\n" + bytes(range(256)) * 32
        tunnel.sock.sendall(payload)
        received = bytearray()
        while len(received) < len(payload):
            data = tunnel.sock.recv(len(payload) - len(received))
            self.assertTrue(data)
            received.extend(data)
        self.assertEqual(bytes(received), payload)
        command = self.commands[0]
        self.assertEqual(command[command.index("-W") + 1], "[2001:db8::1]:2222")
        self.assertEqual(command[command.index("-J") + 1], "first-user@first:2201")
        self.assertEqual(command[-2:], ["--", "last"])
        self.assertIn("BatchMode=yes", command)
        tunnel.close()
        self.assert_closed()

    @unittest.skipUnless(SSH, "OpenSSH ssh is unavailable")
    def test_runtime_config_inherits_real_config_and_forces_batch_mode_on_every_jump(self) -> None:
        original = self.config_file.read_bytes()
        tunnel = self.start_tunnel()
        command = self.commands[0]
        config_file = command[command.index("-F") + 1]
        for alias, host, user, port, key in (
            ("first", "192.0.2.1", "first-user", 2201, self.first_key),
            ("last", "192.0.2.2", "last-user", 2202, self.last_key),
        ):
            with self.subTest(alias=alias):
                result = ssh_config.subprocess.run(
                    [SSH, "-G", "-F", config_file, "--", alias],
                    capture_output=True,
                    text=True,
                    timeout=TRANSFER_TIMEOUT,
                    check=True,
                    shell=False,
                )
                self.assertIn(f"hostname {host}\n", result.stdout)
                self.assertIn(f"user {user}\n", result.stdout)
                self.assertIn(f"port {port}\n", result.stdout)
                self.assertIn(f"identityfile {key.as_posix()}\n", result.stdout)
                self.assertIn("identitiesonly yes\n", result.stdout)
                self.assertIn("batchmode yes\n", result.stdout)
        tunnel.close()
        self.assert_closed()
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_process_exit_delivers_final_output_and_eof(self) -> None:
        tunnel = self.start_tunnel(
            "import sys\nsys.stdout.buffer.write(b'last output')\n"
            "sys.stdout.buffer.flush()\nsys.exit(17)\n"
        )
        self.assertEqual(self.receive_to_eof(tunnel.sock), b"last output")
        self.assertEqual(self.processes[0].wait(timeout=TRANSFER_TIMEOUT), 17)
        tunnel.close()
        self.assert_closed()

    def test_mid_stream_failure_delivers_partial_reply_and_eof(self) -> None:
        tunnel = self.start_tunnel(
            "import sys\ndata = sys.stdin.buffer.read(4096)\n"
            "sys.stdout.buffer.write(data[:137])\nsys.stdout.buffer.flush()\nsys.exit(23)\n"
        )
        payload = bytes(range(256)) * 64
        tunnel.sock.sendall(payload)
        self.assertEqual(self.receive_to_eof(tunnel.sock), payload[:137])
        self.assertEqual(self.processes[0].wait(timeout=TRANSFER_TIMEOUT), 23)
        tunnel.close()
        self.assert_closed()

    def test_client_half_close_preserves_reply_until_remote_eof(self) -> None:
        tunnel = self.start_tunnel(
            ECHO_PROCESS + "sys.stdout.buffer.write(b'final reply')\nsys.stdout.buffer.flush()\n"
        )
        payload = bytes(range(256)) * 64
        tunnel.sock.sendall(payload)
        tunnel.sock.shutdown(socket.SHUT_WR)
        self.assertEqual(self.receive_to_eof(tunnel.sock), payload + b"final reply")
        self.assertEqual(self.processes[0].wait(timeout=TRANSFER_TIMEOUT), 0)
        tunnel.close()
        self.assert_closed()

    def test_close_kills_and_reaps_process_when_termination_times_out(self) -> None:
        tunnel = self.start_tunnel("import time\ntime.sleep(60)\n")
        process = self.processes[0]
        real_wait = process.wait
        with (
            patch.object(process, "terminate") as terminate,
            patch.object(process, "wait") as wait,
            patch.object(process, "kill", wraps=process.kill) as kill,
        ):

            def timed_wait(timeout: float) -> int:
                if wait.call_count == 1:
                    raise jump.subprocess.TimeoutExpired(process.args, timeout)
                return real_wait(timeout=timeout)

            wait.side_effect = timed_wait
            tunnel.close()
            terminate.assert_called_once_with()
            kill.assert_called_once_with()
            self.assertEqual(wait.call_args_list, [call(timeout=jump.CLOSE_TIMEOUT)] * 2)
        self.assert_closed()

    def test_four_megabytes_transfer_simultaneously_in_both_directions(self) -> None:
        tunnel = self.start_tunnel(
            "import hashlib, sys, threading\n"
            "def download():\n"
            " sys.stdout.buffer.write(bytes(reversed(range(256))) * 16384)\n"
            " sys.stdout.buffer.flush()\n"
            "sender = threading.Thread(target=download)\nsender.start()\n"
            "digest = hashlib.sha256()\nsize = 0\n"
            "while data := sys.stdin.buffer.read1(65536):\n"
            " digest.update(data)\n size += len(data)\n"
            "sender.join()\n"
            "sys.stdout.buffer.write(size.to_bytes(8, 'big') + digest.digest())\n"
            "sys.stdout.buffer.flush()\n"
        )
        payload = bytes(range(256)) * 16384
        failures = []

        def upload() -> None:
            try:
                tunnel.sock.sendall(payload)
                tunnel.sock.shutdown(socket.SHUT_WR)
            except OSError as exc:
                failures.append(exc)

        sender = Thread(target=upload, daemon=True)
        sender.start()
        try:
            received = self.receive_to_eof(tunnel.sock)
        finally:
            tunnel.close()
            sender.join(timeout=TRANSFER_TIMEOUT)
        self.assertFalse(sender.is_alive())
        self.assertEqual(failures, [])
        expected = bytes(reversed(range(256))) * 16384
        self.assertEqual(
            received, expected + len(payload).to_bytes(8, "big") + hashlib.sha256(payload).digest()
        )
        self.assert_closed()

    def test_start_failure_closes_both_sockets(self) -> None:
        client, bridge = socket.socketpair()
        with (
            patch("air_ssh.infrastructure.jump.socket.socketpair", return_value=(client, bridge)),
            patch("air_ssh.infrastructure.jump.subprocess.Popen", side_effect=OSError("failed")),
            self.assertRaises(OperationError),
        ):
            JumpTunnel(self.route())
        self.assertEqual((client.fileno(), bridge.fileno()), (-1, -1))


class JumpSessionTests(unittest.TestCase):
    """Ensure every session exit releases forwarding, including failed setup."""

    def setUp(self) -> None:
        self.route = SshRoute("192.0.2.1", 2222, (SshHost("jump", "192.0.2.2", "user", 22),))
        patcher = patch("air_ssh.infrastructure.session.resolve_route", return_value=self.route)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("air_ssh.infrastructure.session.JumpTunnel")
    @patch("netmiko.ConnectHandler")
    def test_controller_uses_resolved_address_and_closes_tunnel_on_disconnect_error(
        self, connect: Mock, tunnel: Mock
    ) -> None:
        connect.return_value.read_channel.side_effect = ["(Cisco Controller) >", "", ""]
        session = open_session(
            Target("lab", "alias", "admin", "test-secret"), io.StringIO(), io.StringIO()
        )
        options = connect.call_args.kwargs
        self.assertEqual((options["host"], options["port"]), ("192.0.2.1", 2222))
        self.assertIs(options["sock"], tunnel.return_value.sock)
        self.assertEqual(options["password"], "test-secret")
        tunnel.return_value.close.assert_not_called()
        connect.return_value.disconnect.side_effect = OSError("disconnect failed")
        with self.assertRaises(OSError):
            session.close()
        tunnel.return_value.close.assert_called_once()

    @patch("air_ssh.infrastructure.session.JumpTunnel")
    @patch("netmiko.ConnectHandler")
    def test_connection_failure_and_interrupt_release_tunnel(
        self, connect: Mock, tunnel: Mock
    ) -> None:
        for failure in (OSError("test-secret"), EOFError("test-secret"), KeyboardInterrupt()):
            with self.subTest(failure=failure):
                tunnel.reset_mock()
                connect.side_effect = failure
                expected = (
                    KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else OperationError
                )
                with self.assertRaises(expected) as raised:
                    open_session(
                        Target("lab", "alias", "admin", "test-secret"), io.StringIO(), io.StringIO()
                    )
                self.assertNotIn("test-secret", str(raised.exception))
                tunnel.return_value.close.assert_called_once()

    @patch("air_ssh.infrastructure.session.JumpTunnel")
    @patch("netmiko.ConnectHandler")
    def test_ap_enable_failure_releases_tunnel(self, connect: Mock, tunnel: Mock) -> None:
        connect.return_value.enable.side_effect = ValueError("wrong secret")
        with self.assertRaises(OperationError):
            open_session(
                Target("ap", "alias", "admin", "test-secret", kind="ap"),
                io.StringIO(),
                io.StringIO(),
            )
        connect.return_value.disconnect.assert_called_once()
        tunnel.return_value.close.assert_called_once()

    @patch("air_ssh.infrastructure.session.JumpTunnel")
    @patch("netmiko.ConnectHandler")
    def test_ap_uses_same_jump_route(self, connect: Mock, tunnel: Mock) -> None:
        session = open_session(
            Target("ap", "alias", "admin", "test-secret", kind="ap"), io.StringIO(), io.StringIO()
        )
        self.assertIsInstance(session, ApSession)
        self.assertIs(connect.call_args.kwargs["sock"], tunnel.return_value.sock)
        session.close()
        tunnel.return_value.close.assert_called_once()
