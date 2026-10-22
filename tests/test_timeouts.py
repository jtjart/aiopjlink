import asyncio
import contextlib
import time
import unittest
from unittest import mock

import aiopjlink
from mock_projector import client_for, raw_tcp_server, until_hung_up, unused_port

TIMEOUT = 0.5


async def hang(*_args, **_kwargs):
    """Stand-in for a coroutine that never completes (until it is cancelled)."""
    await asyncio.sleep(3600)


def make_client(port, **options):
    return client_for(port, timeout=TIMEOUT, **options)


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    """One overall deadline per command, and the error names the phase that ran out of time."""

    async def _expect_timeout(self, port, exc_type=aiopjlink.PJLinkNoConnection):
        """Run a command on `port`, return the exception and check it took about one timeout."""
        start = time.monotonic()
        with self.assertRaises(exc_type) as err:
            await make_client(port).power.get()
        self.assertLess(time.monotonic() - start, TIMEOUT * 2)
        return str(err.exception)

    async def test_connect_phase(self):
        with mock.patch.object(asyncio, "open_connection", hang):
            message = await self._expect_timeout(unused_port())
        self.assertEqual(message, "timeout - projector did not accept the connection in time")

    async def test_greeting_phase(self):
        async with raw_tcp_server(until_hung_up) as server:
            message = await self._expect_timeout(server.port)
        self.assertEqual(message, "timeout - projector did not send a welcome message in time")

    async def test_send_phase(self):
        async def greet_only(reader, writer):
            writer.write(b"PJLINK 0\r")  # No drain(): it is patched out below.
            await until_hung_up(reader, writer)

        async with raw_tcp_server(greet_only) as server:
            with mock.patch.object(asyncio.StreamWriter, "drain", hang):
                message = await self._expect_timeout(server.port)
        self.assertEqual(message, "timeout - projector did not accept the command in time")

    async def test_response_phase(self):
        async def no_answer(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            await until_hung_up(reader, writer)

        async with raw_tcp_server(no_answer) as server:
            message = await self._expect_timeout(server.port)
        self.assertEqual(message, "timeout - projector did not respond in time")

    async def test_deadline_covers_the_whole_command(self):
        """Phases that are each within the timeout, but together exceed it, still time out."""
        delay = TIMEOUT * 0.7

        async def slow(reader, writer):
            await asyncio.sleep(delay)
            writer.write(b"PJLINK 0\r")
            await reader.readuntil(b"\r")
            await asyncio.sleep(delay)
            with contextlib.suppress(ConnectionError):
                writer.write(b"%1POWR=0\r")
                await writer.drain()
            await until_hung_up(reader, writer)

        async with raw_tcp_server(slow) as server:
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await make_client(server.port).power.get()

    async def test_close_is_bounded(self):
        """A connection that never finishes closing does not stall the command (one connection per command)."""

        async def answer(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.readuntil(b"\r")
            writer.write(b"%1POWR=0\r")
            await writer.drain()
            await until_hung_up(reader, writer)

        async with raw_tcp_server(answer) as server:
            start = time.monotonic()
            with mock.patch.object(asyncio.StreamWriter, "wait_closed", hang):
                status = await make_client(server.port, persistent=False).power.get()
            elapsed = time.monotonic() - start
        self.assertEqual(status, aiopjlink.Power.State.OFF)
        self.assertLess(elapsed, 2)
