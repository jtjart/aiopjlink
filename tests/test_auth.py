import asyncio
import hashlib
import unittest
from unittest.mock import patch

import aiopjlink2
from aiopjlink2._debug import redact_debug_payload
from aiopjlink2.client import _Session
from mock_projector import client_for, mock_tcp_pjlink, raw_tcp_server, unused_port


class DebugLoggingTests(unittest.TestCase):
    """The redaction helper hides the one-time auth token in debug logs."""

    def test_debug_redaction(self) -> None:
        self.assertEqual(redact_debug_payload("PJLINK 1 123456"), "PJLINK 1 <redacted>")
        self.assertEqual(redact_debug_payload("PJLINK 0\r"), "PJLINK 0\r")


class AuthTests(unittest.IsolatedAsyncioTestCase):
    """PJLink authentication behaves as expected."""

    async def test_auth_none(self) -> None:
        """Tests a connection with no authentication."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")

            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                client = server.client()
                self.addAsyncCleanup(client.close)
                value = await client.power.get()
                self.assertEqual(value, aiopjlink2.Power.State.OFF)

    async def test_auth_malformed(self) -> None:
        """Tests the projector sending back a malformed welcome message generates a `PJLinkProtocolError`."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK XXX\r")

            with self.assertRaises(aiopjlink2.PJLinkProtocolError):
                link = server.client()
                await link.power.get()

    async def test_auth_malformed_security_message(self) -> None:
        """Auth is announced (`1`) but the token is not separated by a space: `PJLinkProtocolError`."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1X21d0e96e\r")

            # Rejected before any command (or password hash) is sent.
            with self.assertRaises(aiopjlink2.PJLinkProtocolError) as err:
                link = server.client(password="abc123")
                await link.power.get()
            self.assertIn("unrecognised auth method", str(err.exception))

    async def test_auth_no_welcome(self) -> None:
        """A projector that accepts the connection but sends no welcome message is a `PJLinkNoConnectionError`."""

        async with mock_tcp_pjlink() as server:
            # No `open_and_send`: the projector accepts the connection but sends no welcome message.
            # That is the same error as for a missing response to a command.
            with self.assertRaises(aiopjlink2.PJLinkNoConnectionError) as err:
                link = server.client(timeout_seconds=0.5)
                await link.power.get()

            self.assertIn("welcome message", str(err.exception))

    async def test_auth_no_server(self) -> None:
        """Tests that the client honours the timeout if no server responds to the connection."""

        # CONDITION 1: Nothing listens on the port: refused, or a timeout where the OS drops the packet.
        with self.assertRaises(aiopjlink2.PJLinkNoConnectionError) as err:
            link = client_for(unused_port(), timeout_seconds=0.5)
            await link.power.get()
        # Accept either error message for compatibility
        self.assertTrue(
            str(err.exception).startswith("timeout - projector did not accept the connection in time")
            or str(err.exception).startswith("connection failed"),
            f"Unexpected error message: {err.exception!s}",
        )

        # CONDITION 2: The host cannot be reached by the OS.
        with self.assertRaises(aiopjlink2.PJLinkNoConnectionError) as err:
            link = aiopjlink2.PJLink(address="0.0.0.0", port=unused_port(), password=None, timeout_seconds=0.5)
            await link.power.get()
        self.assertIn("connection failed", str(err.exception))

    async def test_auth_valid_pw(self) -> None:
        """Tests a connection with valid authentication."""

        # Server sends the auth challenge: token='21d0e96e'; password='abc123'
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            # The digest the projector expects in front of the command: MD5 of the token followed by the password.
            salted_password = hashlib.md5(b"21d0e96eabc123").hexdigest().encode()
            cmd = bytes(salted_password) + b"%1POWR ?\r"
            async with server.when(cmd, respond_with=b"%1POWR=0\r"):
                link = server.client(password="abc123", authentication=aiopjlink2.PJAuth.MD5)
                self.addAsyncCleanup(link.close)
                await link.power.get()

    async def test_auth_invalid_pw(self) -> None:
        """Tests a connection with invalid authentication."""

        # Server sends the auth challenge: token='21d0e96e'; password='abc123'
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            # The client sends the digest of the wrong password, which the projector rejects.
            salted_password = hashlib.md5(b"21d0e96eINVALIDPW").hexdigest().encode()
            cmd = bytes(salted_password) + b"%1POWR ?\r"
            async with server.when(cmd, respond_with=b"PJLINK ERRA\r"):
                with self.assertRaises(aiopjlink2.PJLinkAuthenticationError):
                    link = server.client(password="INVALIDPW", authentication=aiopjlink2.PJAuth.MD5)
                    await link.power.get()

    async def test_auth_missing_pw(self) -> None:
        """Tests a projector that wants a password when none was given."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            with self.assertRaises(aiopjlink2.PJLinkAuthenticationError) as err:
                link = server.client()
                await link.power.get()
            self.assertEqual(str(err.exception), "password required")

    async def test_auth_wrong_password_projector_hangs_up(self) -> None:
        """A projector that closes instead of sending ERRA is reported as a password problem."""

        async def hang_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(b"PJLINK 1 21d0e96e\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.close()

        async with raw_tcp_server(hang_up) as server:
            link = server.client(password="wrong", timeout_seconds=2.0)
            with self.assertRaises(aiopjlink2.PJLinkAuthenticationError):
                await link.power.get()

    async def test_send_failure_is_not_reported_as_a_password_error(self) -> None:
        """A failure while sending the digest is a connection error, not a rejected password."""

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.write(b"PJLINK 1 21d0e96e\r")
            await writer.drain()
            await reader.read()
            writer.close()

        async def fail_send(link: aiopjlink2.PJLink, session: _Session, command_line: str) -> None:
            session.digest_sent = True
            raise aiopjlink2.PJLinkConnectionClosedError("simulated send failure")

        async with raw_tcp_server(handler) as server:
            link = server.client(timeout_seconds=0.5)
            with (
                patch.object(aiopjlink2.PJLink, "_send", fail_send),
                self.assertRaises(aiopjlink2.PJLinkConnectionClosedError),
            ):
                await link.power.get()

    async def test_hang_up_after_successful_auth_is_a_connection_error(self) -> None:
        """Once the password has worked, a later hang-up is not blamed on the password."""
        connections = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal connections
            connections += 1
            writer.write(b"PJLINK 1 21d0e96e\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            if connections == 1:
                writer.write(b"%1POWR=1\r")
                await writer.drain()
            writer.close()

        async with raw_tcp_server(handler) as server:
            link = server.client(
                password="abc123", timeout_seconds=0.5, persistent=False, authentication=aiopjlink2.PJAuth.MD5
            )
            await link.power.get()
            with self.assertRaises(aiopjlink2.PJLinkConnectionClosedError):
                await link.power.get()
