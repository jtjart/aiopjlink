"""Every way the projector can be unreachable or stop talking is a `PJLinkConnectionError`."""

import socket
import struct
import unittest

import aiopjlink
from mock_projector import mock_tcp_pjlink, raw_tcp_server


def _reset(writer):
    """Close the connection with a TCP RST instead of a FIN."""
    sock = writer.get_extra_info("socket")
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    writer.transport.abort()


class ConnectionErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _assert_connection_error(self, expected):
        """Run a command and check it fails with `expected`, which is also a `PJLinkConnectionError`."""
        client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
        with self.assertRaises(aiopjlink.PJLinkConnectionError) as ctx:
            await client.power.get()
        self.assertIsInstance(ctx.exception, expected)
        return ctx.exception

    async def test_connect_refused(self):
        """Nothing listens on the port."""
        await self._assert_connection_error(aiopjlink.PJLinkNoConnection)

    async def test_no_greeting(self):
        """TCP is accepted, but the projector never says `PJLINK ...`."""
        async with mock_tcp_pjlink():
            err = await self._assert_connection_error(aiopjlink.PJLinkNoConnection)
        self.assertIn("welcome message", str(err))

    async def test_no_response_to_command(self):
        """Greeting is fine, but the command is never answered."""
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            async with server.when(b"%1POWR ?\r", respond_with=b""):
                err = await self._assert_connection_error(aiopjlink.PJLinkNoConnection)
        self.assertIn("did not respond in time", str(err))

    async def test_closed_before_greeting(self):
        async def close(reader, writer):
            writer.close()

        async with raw_tcp_server(close):
            await self._assert_connection_error(aiopjlink.PJLinkConnectionClosed)

    async def test_closed_after_command(self):
        async def hang_up(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.close()

        async with raw_tcp_server(hang_up):
            await self._assert_connection_error(aiopjlink.PJLinkConnectionClosed)

    async def test_reset_before_greeting(self):
        async def reset(reader, writer):
            _reset(writer)

        async with raw_tcp_server(reset):
            await self._assert_connection_error(aiopjlink.PJLinkConnectionClosed)

    async def test_reset_after_command(self):
        async def reset(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            _reset(writer)

        async with raw_tcp_server(reset):
            await self._assert_connection_error(aiopjlink.PJLinkConnectionClosed)

    async def test_bad_data_is_not_a_connection_error(self):
        """A projector that talks nonsense is reachable: that is a `PJLinkProtocolError`."""
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=0.5)
            async with server.when(b"%1POWR ?\r", respond_with=b"%\r"):
                with self.assertRaises(aiopjlink.PJLinkProtocolError) as ctx:
                    await client.power.get()
        self.assertNotIsInstance(ctx.exception, aiopjlink.PJLinkConnectionError)
