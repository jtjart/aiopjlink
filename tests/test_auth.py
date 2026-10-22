import hashlib
import unittest
from unittest.mock import patch

import aiopjlink
from mock_projector import client_for, mock_tcp_pjlink, raw_tcp_server, unused_port


class DebugLoggingTests(unittest.TestCase):
    """The redaction helper hides the one-time auth token in debug logs."""

    def test_debug_redaction(self):
        from aiopjlink._debug import redact_debug_payload

        self.assertEqual(redact_debug_payload("PJLINK 1 123456"), "PJLINK 1 <redacted>")
        self.assertEqual(redact_debug_payload("PJLINK 0\r"), "PJLINK 0\r")


class AuthTests(unittest.IsolatedAsyncioTestCase):
    """PJLink authentication behaves as expected."""

    async def test_auth_none(self):
        """Tests a connection with no authentication."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")

            # Prime the server to handle a power request.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                # Send the power request and check the response is expected.
                client = server.client()
                self.addAsyncCleanup(client.close)
                value = await client.transmit("POWR", "?", pjclass="1")
                self.assertEqual(value, "0")

    async def test_auth_malformed(self):
        """Tests the projector sending back a malformed welcome message generates a `PJLinkProtocolError`."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK XXX\r")

            # Expect to see a protocol error when we connect.
            with self.assertRaises(aiopjlink.PJLinkProtocolError):
                link = server.client()
                await link.power.get()

    async def test_auth_malformed_security_message(self):
        """Auth is announced (`1`) but the token is not separated by a space: `PJLinkProtocolError`."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1X21d0e96e\r")

            # Rejected before any command (or password hash) is sent.
            with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                link = server.client(password="abc123")
                await link.power.get()
            self.assertIn("unrecognised auth method", str(err.exception))

    async def test_auth_no_welcome(self):
        """A projector that accepts the connection but sends no welcome message is a `PJLinkNoConnection`."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            # Do not send a message (i.e. the one commented out below).
            # server.open_and_send(b'PJLINK XXX\r')

            # Expect the same error as for a missing response to a command.
            with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                link = server.client(timeout=0.5)
                await link.power.get()

            self.assertIn("welcome message", str(err.exception))

    async def test_auth_no_server(self):
        """Tests that the client honours the timeout if no server responds to the connection."""

        # CONDITION 1: The host can be reached by the OS but no response (aiotimeout).
        with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
            link = client_for(unused_port(), timeout=0.5)
            await link.power.get()
        # Accept either error message for compatibility
        self.assertTrue(
            str(err.exception).startswith("timeout - projector did not accept the connection in time")
            or str(err.exception).startswith("connection failed"),
            f"Unexpected error message: {err.exception!s}",
        )

        # CONDITION 2: The host cannot be reached by the OS.
        with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
            link = aiopjlink.PJLink(address="0.0.0.0", port=unused_port(), password=None, timeout=0.5)
            await link.power.get()
        self.assertIn("connection failed", str(err.exception))

    async def test_auth_valid_pw(self):
        """Tests a connection with valid authentication."""

        # Server sends the auth challenge: token='21d0e96e'; password='abc123'
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            # Calcuate the expected projector behaviour.
            # NOTE: Our client implementation always sends a `POWR ?` since that is
            # a commonly implemented command.
            salted_password = hashlib.md5(b"21d0e96eabc123").hexdigest().encode()
            cmd = bytes(salted_password) + b"%1POWR ?\r"
            async with server.when(cmd, respond_with=b"%1POWR=0\r"):
                # Send the power request and check the response is expected.
                link = server.client(password="abc123")
                self.addAsyncCleanup(link.close)
                await link.power.get()

    async def test_auth_invalid_pw(self):
        """Tests a connection with invalid authentication."""

        # Server sends the auth challenge: token='21d0e96e'; password='abc123'
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            # Calcuate the expected projector behaviour.
            salted_password = hashlib.md5(b"21d0e96eINVALIDPW").hexdigest().encode()
            cmd = bytes(salted_password) + b"%1POWR ?\r"
            async with server.when(cmd, respond_with=b"PJLINK ERRA\r"):
                # Send the power request and check the response is expected.
                with self.assertRaises(aiopjlink.PJLinkPassword):
                    link = server.client(password="INVALIDPW")
                    await link.power.get()

    async def test_auth_missing_pw(self):
        """Tests a projector that wants a password when none was given."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            with self.assertRaises(aiopjlink.PJLinkPassword) as err:
                link = server.client()
                await link.power.get()
            self.assertEqual(str(err.exception), "password required")

    async def test_auth_wrong_password_projector_hangs_up(self):
        """A projector that closes instead of sending ERRA is reported as a password problem."""

        async def hang_up(reader, writer):
            writer.write(b"PJLINK 1 21d0e96e\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.close()

        async with raw_tcp_server(hang_up) as server:
            link = server.client(password="wrong", timeout=0.5)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()

    async def test_send_failure_is_not_reported_as_a_password_error(self):
        """A failure while sending the digest is a connection error, not a rejected password."""

        async def handler(reader, writer):
            writer.write(b"PJLINK 1 21d0e96e\r")
            await writer.drain()
            await reader.read()
            writer.close()

        async def fail_send(transport, session, cstring):
            session.digest_sent = True
            raise aiopjlink.PJLinkConnectionClosed("simulated send failure")

        async with raw_tcp_server(handler) as server:
            link = server.client(timeout=0.5)
            with patch.object(aiopjlink._transport.Transport, "_send", fail_send):
                with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                    await link.power.get()

    async def test_hang_up_after_successful_auth_is_a_connection_error(self):
        """Once the password has worked, a later hang-up is not blamed on the password."""
        connections = 0

        async def handler(reader, writer):
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
            link = server.client(password="abc123", timeout=0.5, persistent=False)
            await link.power.get()
            with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                await link.power.get()
