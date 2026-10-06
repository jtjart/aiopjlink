import unittest

import aiopjlink
from aiopjlink._protocol import format_command, parse_response
from mock_projector import (
    mock_client_server_noauth,
    mock_tcp_pjlink,
    raw_tcp_server,
)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    """PJLink protocol managment behaves as expected."""

    async def test_response_parsing_high_level(self):
        """Check that responses are handled correctly by the client."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None)

            # Unxpected command sent as a result of a request.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1ROWP=A\r"):
                with self.assertRaises(aiopjlink.PJLinkProtocolError):
                    await client.power.get()

    async def test_command_construction(self):
        """Test that command formatting accepts valid values and raises errors if out of spec."""
        # Normal commands.
        result = format_command("ABCD", "???", pjclass="1")
        self.assertEqual(result, "%1ABCD ???\r")

        result = format_command("EFGH", "1", pjclass="1")
        self.assertEqual(result, "%1EFGH 1\r")

        result = format_command("IJKL", "9999999", pjclass="1")
        self.assertEqual(result, "%1IJKL 9999999\r")

        result = format_command("ABCD", "?", pjclass="2")
        self.assertEqual(result, "%2ABCD ?\r")

        # Bad commands.
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            result = format_command("abcd", "?", pjclass="1")
        self.assertEqual(str(err.exception), "command is not uppercase")

        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            result = format_command("ABCDE", "?", pjclass="1")
        self.assertEqual(str(err.exception), "command is not 4 bytes")

        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            large_param = "X" * 129
            result = format_command("ABCD", large_param, pjclass="1")
        self.assertEqual(str(err.exception), "command param is larger than 128 bytes")

        with self.assertRaises(ValueError) as err:
            result = format_command("ABCD", "?", pjclass="3")
        self.assertEqual(str(err.exception), "'3' is not a valid PJClass")

    async def test_bad_command_rejected_before_connecting(self):
        """A malformed command fails fast, without touching the network."""

        # No server is running: if the library tried to connect first,
        # this would be a `PJLinkNoConnection` instead.
        link = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            await link.transmit("abcd", "?", pjclass="1")
        self.assertEqual(str(err.exception), "command is not uppercase")

    async def test_response_parsing(self):
        """Ensure that errors generate the correct responses."""

        # Valid data.
        command, parameter = parse_response(data="%1ABCD=5\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(command, "ABCD")
        self.assertEqual(parameter, "5")

        # Response too short to be a PJLink response.
        for data in ("", "\r", "%\r", "%1ABCD\r"):
            with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                parse_response(data=data, expect_command="ABCD", expect_pjclass="1")
            self.assertEqual(str(err.exception), "unexpected response - too short")

        # Bad response header.
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            parse_response(data="#1ABCD=5\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unexpected response header")

        # Bad class version.
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            parse_response(data="%2ABCD=5\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unexpected response protocol class")

        # Bad separator.
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            parse_response(data="%1ABCD/5\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unexpected response separator")

        # Bad command length.
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            parse_response(data="%1ABCDE/5\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unexpected response separator")

        # Unexpected command (not the one that was asked for).
        with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
            parse_response(data="%1ABCD=5\r", expect_command="XXXX", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unexpected response command")

        # ERR1 - unsupported command
        with self.assertRaises(aiopjlink.PJLinkERR1) as err:
            parse_response(data="%1ABCD=ERR1\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unsupported command")

        # ERR2 - out of parameter
        with self.assertRaises(aiopjlink.PJLinkERR2) as err:
            parse_response(data="%1ABCD=ERR2\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "out of parameter")

        # ERR3 - unavailable in the current state
        with self.assertRaises(aiopjlink.PJLinkERR3) as err:
            parse_response(data="%1ABCD=ERR3\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "unavailable in the current state")

        # ERR4 - projector or display failure
        with self.assertRaises(aiopjlink.PJLinkERR4) as err:
            parse_response(data="%1ABCD=ERR4\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "projector or display failure")

        # Check error parsing is case insensitive (from projector) and error
        # parsing is handled in the same way too (Postel's law).
        with self.assertRaises(aiopjlink.PJLinkERR4) as err:
            parse_response(data="%1abcd=err4\r", expect_command="ABCD", expect_pjclass="1")
        self.assertEqual(str(err.exception), "projector or display failure")

        # Check that a respone does not fail if there is a CR right after
        # an equals (e.g. §4.12 of the spec)
        command, param = parse_response(data="%1INF2=\r", expect_command="INF2", expect_pjclass="1")
        self.assertEqual(command, "INF2")
        self.assertEqual(param, "")

    async def test_response_too_short(self):
        """A truncated response is a protocol error, not an `IndexError`."""
        async with mock_client_server_noauth() as (server, client):
            async with server.when(b"%1POWR ?\r", respond_with=b"%\r"):
                with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                    await client.power.get()
            self.assertEqual(str(err.exception), "unexpected response - too short")

    async def test_response_timeout(self):
        """A projector that accepts the connection but never answers the command is a `PJLinkNoConnection`."""
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)

            # The mock reads the command but sends nothing back.
            async with server.when(b"%1POWR ?\r", respond_with=b""):
                with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                    await client.power.get()
            self.assertIn("did not respond in time", str(err.exception))

    async def test_connection_closed_before_response(self):
        """A projector that hangs up in the middle of a command is a `PJLinkConnectionClosed`."""

        async def hang_up(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.close()

        async with raw_tcp_server(hang_up):
            client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
            with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                await client.power.get()

    async def test_undecodable_response(self):
        """A response that is not valid text is a `PJLinkProtocolError`, not a `UnicodeDecodeError`."""

        async def send_garbage(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.write(b"\xff\xfe\xfd\r")
            await writer.drain()
            writer.close()

        async with raw_tcp_server(send_garbage):
            client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
            with self.assertRaises(aiopjlink.PJLinkProtocolError):
                await client.power.get()
