import hashlib
import unittest

import aiopjlink
from mock_projector import mock_tcp_pjlink


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
                client = aiopjlink.PJLink(address="127.0.0.1", password=None)
                value = await client.transmit("POWR", "?", pjclass="1")
                self.assertEqual(value, "0")

    async def test_auth_malformed(self):
        """Tests the projector sending back a malformed welcome message generates a `PJLinkProtocolError`."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK XXX\r")

            # Expect to see a protocol error when we connect.
            with self.assertRaises(aiopjlink.PJLinkProtocolError):
                link = aiopjlink.PJLink(address="127.0.0.1", password=None)
                await link.power.get()

    async def test_auth_malformed_security_message(self):
        """Auth is announced (`1`) but the token is not separated by a space: `PJLinkProtocolError`."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1X21d0e96e\r")

            # Rejected before any command (or password hash) is sent.
            with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                link = aiopjlink.PJLink(address="127.0.0.1", password="abc123")
                await link.power.get()
            self.assertIn("unrecognised auth method", str(err.exception))

    async def test_auth_no_welcome(self):
        """Tests the projector not sending a welcome message generates a `PJLinkProtocolError`"""

        # Start server with no auth.
        async with mock_tcp_pjlink():
            # Do not send a message (i.e. the one commented out below).
            # server.open_and_send(b'PJLINK XXX\r')

            # Expect to see a protocol error when we connect.
            with self.assertRaises(aiopjlink.PJLinkProtocolError):
                link = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
                await link.power.get()

    async def test_auth_no_server(self):
        """Tests that the client honours the timeout if no server responds to the connection."""

        # CONDITION 1: The host can be reached by the OS but no response (aiotimeout).
        with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
            link = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
            await link.power.get()
        # Accept either error message for compatibility
        self.assertTrue(
            str(err.exception).startswith("timeout - projector did not accept the connection in time")
            or str(err.exception).startswith("os timeout"),
            f"Unexpected error message: {err.exception!s}",
        )

        # CONDITION 2: The host cannot be reached by the OS.
        with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
            link = aiopjlink.PJLink(address="0.0.0.0", password=None, timeout=0.5)
            await link.power.get()
        self.assertIn("os timeout", str(err.exception))

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
                link = aiopjlink.PJLink(address="127.0.0.1", password="abc123")
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
                    link = aiopjlink.PJLink(address="127.0.0.1", password="INVALIDPW")
                    await link.power.get()

    async def test_auth_missing_pw(self):
        """Tests a projector that wants a password when none was given."""

        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            with self.assertRaises(aiopjlink.PJLinkPassword) as err:
                link = aiopjlink.PJLink(address="127.0.0.1", password=None)
                await link.power.get()
            self.assertEqual(str(err.exception), "password required")
