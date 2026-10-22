"""Connection handling: one connection reused for several commands, or one connection per command.

The spec allows both (§5.3, §5.4); `persistent` chooses. These tests count the connections a
projector sees and check that a reused connection never gives a wrong answer.
"""

import asyncio
import hashlib
import time
import unittest
from unittest import mock

import aiopjlink
from aiopjlink._transport import _Session
from mock_projector import raw_tcp_server

ON = b"%1POWR=1\r"
TIMEOUT = 2.0


class FakeProjector:
    """A projector that answers every command, counts connections and records the lines it receives.

    `replies` are used in order for the commands received (on whatever connection); once they run out
    the answer is `ON`. `delays` maps a command number (from 0) to seconds to wait before answering.
    When `response_gate` is set, replies wait until that event is set.
    """

    def __init__(self, *, token=None, replies=(), delays=None, response_gate=None, hang_up_after_answer=False):
        self.token = token
        self.replies = list(replies)
        self.delays = delays or {}
        self.response_gate = response_gate
        self.hang_up_after_answer = hang_up_after_answer
        self.connections = 0
        self.open_connections = 0
        self.lines: list[bytes] = []
        self.command_received = asyncio.Event()
        self.connection_closed = asyncio.Event()

    async def wait_for_closed_connections(self, count):
        while self.connections - self.open_connections < count:
            self.connection_closed.clear()
            if self.connections - self.open_connections >= count:
                break
            await asyncio.wait_for(self.connection_closed.wait(), timeout=5)

    async def __call__(self, reader, writer):
        self.connections += 1
        self.open_connections += 1
        try:
            writer.write(b"PJLINK 0\r" if self.token is None else b"PJLINK 1 " + self.token + b"\r")
            await writer.drain()
            while True:
                line = await reader.readuntil(b"\r")
                number = len(self.lines)
                self.lines.append(line)
                self.command_received.set()
                await asyncio.sleep(self.delays.get(number, 0))
                if self.response_gate is not None:
                    await self.response_gate.wait()
                writer.write(self.replies[number] if number < len(self.replies) else ON)
                await writer.drain()
                if self.hang_up_after_answer:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.open_connections -= 1
            writer.close()
            self.connection_closed.set()


def client(server, timeout=TIMEOUT, **options):
    return server.client(timeout=timeout, **options)


class PersistentTests(unittest.IsolatedAsyncioTestCase):
    """The default: the connection is kept for the next command."""

    async def test_default_is_persistent(self):
        self.assertTrue(aiopjlink.PJLink(address="127.0.0.1").persistent)
        self.assertFalse(aiopjlink.PJLink(address="127.0.0.1", persistent=False).persistent)

    async def test_follow_up_commands_reuse_the_connection(self):
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server, client(server) as link:
            for _ in range(3):
                self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 1)
        self.assertEqual(len(projector.lines), 3)

    async def test_concurrent_commands_share_the_connection(self):
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server, client(server) as link:
            results = await asyncio.gather(*(link.power.get() for _ in range(5)))
        self.assertEqual(results, [aiopjlink.Power.State.ON] * 5)
        self.assertEqual(projector.connections, 1)

    async def test_digest_is_sent_with_the_first_command_only(self):
        """§5.3: after the first command the authentication data may be left out."""
        projector = FakeProjector(token=b"21d0e96e")
        digest = hashlib.md5(b"21d0e96eabc123").hexdigest().encode()
        async with raw_tcp_server(projector) as server:
            link = server.client(password="abc123", timeout=TIMEOUT)
            await link.power.get()
            await link.power.get()
            self.assertEqual(projector.lines, [digest + b"%1POWR ?\r", b"%1POWR ?\r"])

            # A new connection has to authenticate again.
            await link.close()
            await link.power.get()
            await link.close()
            self.assertEqual(projector.lines[2], digest + b"%1POWR ?\r")

    async def test_projector_error_keeps_the_connection(self):
        """ERR3 is a complete answer: the connection is fine and carries the next command."""
        projector = FakeProjector(replies=[b"%1POWR=ERR3\r"])
        async with raw_tcp_server(projector) as server, client(server) as link:
            with self.assertRaises(aiopjlink.PJLinkNotReady):
                await link.power.get()
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 1)

    async def test_timeout_drops_the_connection(self):
        """A late answer must not be taken for the answer to the next command."""
        projector = FakeProjector(replies=[b"%1POWR=0\r"], delays={0: TIMEOUT * 1.4})
        async with raw_tcp_server(projector) as server, client(server) as link:
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await link.power.get()
            # The late "0" would be read here if the connection had been kept.
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 2)

    async def test_cancelled_command_drops_the_connection(self):
        """Same for a command whose caller gave up (e.g. a cancelled service call)."""
        response_gate = asyncio.Event()
        projector = FakeProjector(replies=[b"%1POWR=0\r"], response_gate=response_gate)
        async with raw_tcp_server(projector) as server, client(server, timeout=10) as link:
            task = asyncio.create_task(link.power.get())
            await asyncio.wait_for(projector.command_received.wait(), timeout=5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            response_gate.set()
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 2)

    async def test_connection_closed_by_the_projector_is_replaced(self):
        """The projector drops a silent connection (§5.4): the next command connects again, no error."""
        projector = FakeProjector(hang_up_after_answer=True)
        async with raw_tcp_server(projector) as server, client(server) as link:
            for connection_number in range(3):
                self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
                await projector.wait_for_closed_connections(connection_number + 1)
        self.assertEqual(projector.connections, 3)

    async def test_query_is_repeated_when_the_kept_connection_is_dead(self):
        """The projector hangs up right when the next query is sent: it is repeated on a new connection."""
        projector = FakeProjector(hang_up_after_answer=True)
        async with raw_tcp_server(projector) as server, client(server) as link:
            await link.power.get()
            await projector.wait_for_closed_connections(1)
            # Pretend not to have noticed the hang-up yet, as when it happens in the same instant.
            with mock.patch.object(_Session, "usable", new_callable=mock.PropertyMock, return_value=True):
                self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 2)

    async def test_command_that_changes_something_is_not_repeated(self):
        """The projector may have carried it out before it hung up, so the caller gets the error."""
        projector = FakeProjector(hang_up_after_answer=True)
        async with raw_tcp_server(projector) as server, client(server) as link:
            await link.power.get()
            await projector.wait_for_closed_connections(1)
            with mock.patch.object(_Session, "usable", new_callable=mock.PropertyMock, return_value=True):
                with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                    await link.power.turn_on()
            # The failed connection was dropped: the next command works.
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        # One connection for the first query, one for the last. A repeat would have needed a third.
        self.assertEqual(projector.connections, 2)

    async def test_idle_connection_is_released(self):
        """A connection nobody uses is given back, so another controller can get in."""
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server, client(server, idle_timeout=0.1) as link:
            await link.power.get()
            self.assertEqual(projector.open_connections, 1)
            await projector.wait_for_closed_connections(1)
            self.assertEqual(projector.open_connections, 0)
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
        self.assertEqual(projector.connections, 2)

    async def test_idle_timeout_must_be_positive(self):
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                aiopjlink.PJLink(address="127.0.0.1", idle_timeout=bad)

    async def test_short_idle_timeout_gives_one_connection_per_burst(self):
        """Three commands at once share a connection, which is closed before the next poll.

        This is what the Home Assistant integration did before it used this library: one connection
        per update, and still only one authentication per update.
        """
        projector = FakeProjector(token=b"21d0e96e")
        digest = hashlib.md5(b"21d0e96eabc123").hexdigest().encode()
        async with raw_tcp_server(projector) as server:
            link = server.client(password="abc123", timeout=TIMEOUT, idle_timeout=0.2)
            for poll in range(3):  # Three polls.
                for _ in range(3):  # Three commands per poll.
                    await link.power.get()
                await projector.wait_for_closed_connections(poll + 1)
                self.assertEqual(projector.open_connections, 0)
        self.assertEqual(projector.connections, 3)
        # The digest went out once per connection, not once per command.
        self.assertEqual(sum(line.startswith(digest) for line in projector.lines), 3)
        self.assertEqual(len(projector.lines), 9)

    async def test_close_releases_the_connection(self):
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server:
            link = client(server)
            await link.power.get()
            await link.close()
            await link.close()  # Safe to repeat.
            await projector.wait_for_closed_connections(1)
            self.assertEqual(projector.open_connections, 0)

            # Still usable: it connects again.
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
            await link.close()
        self.assertEqual(projector.connections, 2)

    async def test_close_before_any_command(self):
        await aiopjlink.PJLink(address="127.0.0.1").close()

    async def test_close_is_bounded(self):
        """A connection that never finishes closing does not stall `close`."""

        async def hang(*_args, **_kwargs):
            await asyncio.sleep(3600)

        async with raw_tcp_server(FakeProjector()) as server:
            link = client(server)
            await link.power.get()
            with mock.patch("aiopjlink._transport._CLOSE_TIMEOUT", 0.1):
                with mock.patch.object(asyncio.StreamWriter, "wait_closed", hang):
                    start = time.monotonic()
                    await link.close()
            self.assertLess(time.monotonic() - start, 1)


class PerCommandTests(unittest.IsolatedAsyncioTestCase):
    """`persistent=False`: every command has a connection of its own, as §5.4 describes."""

    async def test_every_command_opens_and_closes_a_connection(self):
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server:
            link = client(server, persistent=False)
            for connection_number in range(3):
                self.assertEqual(await link.power.get(), aiopjlink.Power.State.ON)
                await projector.wait_for_closed_connections(connection_number + 1)
                self.assertEqual(projector.open_connections, 0)
        self.assertEqual(projector.connections, 3)

    async def test_idle_timeout_does_not_apply(self):
        projector = FakeProjector()
        async with raw_tcp_server(projector) as server:
            link = client(server, persistent=False, idle_timeout=30)
            await link.power.get()
            await link.power.get()
            await projector.wait_for_closed_connections(2)
            self.assertEqual(projector.open_connections, 0)
        self.assertEqual(projector.connections, 2)

    async def test_digest_is_sent_with_every_command(self):
        projector = FakeProjector(token=b"21d0e96e")
        digest = hashlib.md5(b"21d0e96eabc123").hexdigest().encode()
        async with raw_tcp_server(projector) as server:
            link = server.client(password="abc123", timeout=TIMEOUT, persistent=False)
            await link.power.get()
            await link.power.get()
        self.assertEqual(projector.lines, [digest + b"%1POWR ?\r"] * 2)

    async def test_close_does_nothing(self):
        async with raw_tcp_server(FakeProjector()) as server:
            link = client(server, persistent=False)
            await link.close()
            await link.power.get()
            await link.close()
