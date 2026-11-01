"""Data nobody asked for on a kept connection is not the answer to the next command.

Seen on a real projector: it acknowledges `%1POWR 1` with `%1powr=OK` and then sends a `%1powr=0` line of its
own. Taken for the answer to the next command, that line made an `ERST ?` fail with "unexpected response
command", and would have made a `POWR ?` return the wrong state without any error.
"""

import asyncio
import unittest

import aiopjlink
from mock_projector import raw_tcp_server

TIMEOUT = 2.0


class StrayLineProjector:
    """A projector that sends a `%1powr=0` line of its own after it has acknowledged a power-on command.

    `stray_delay` is how long after the acknowledgement it comes. With `same_segment` the two lines are sent
    together. It answers `ERST ?` with "no errors" and `POWR ?` with 3 (warming up).
    """

    def __init__(self, *, stray_delay=0.1, same_segment=False):
        self.stray_delay = stray_delay
        self.same_segment = same_segment
        self.connections = 0
        self.lines = []

    async def __call__(self, reader, writer):
        self.connections += 1
        writer.write(b"PJLINK 0\r")
        await writer.drain()
        try:
            while True:
                line = await reader.readuntil(b"\r")
                self.lines.append(line)
                if line == b"%1POWR 1\r":
                    if self.same_segment:
                        writer.write(b"%1powr=OK\r%1powr=0\r")
                    else:
                        writer.write(b"%1powr=OK\r")
                        asyncio.get_running_loop().call_later(self.stray_delay, writer.write, b"%1powr=0\r")
                elif line == b"%1ERST ?\r":
                    writer.write(b"%1erst=000000\r")
                elif line == b"%1POWR ?\r":
                    writer.write(b"%1powr=3\r")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


class UnsolicitedDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_command_is_not_broken_by_it(self):
        """The command from the bug report: power on, wait, ask for the errors."""
        projector = StrayLineProjector()
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.power.turn_on()
            await asyncio.sleep(0.4)
            errors = await link.errors.query()
        self.assertEqual(set(errors.values()), {aiopjlink.Errors.Level.OK})

    async def test_it_is_not_taken_for_the_answer(self):
        """The worse case: the same command, so nothing looks wrong. The projector is warming up, not off."""
        projector = StrayLineProjector()
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.power.turn_on()
            await asyncio.sleep(0.4)
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.WARMING)

    async def test_two_lines_arriving_together(self):
        projector = StrayLineProjector(same_segment=True)
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.power.turn_on()
            await asyncio.sleep(0.1)
            self.assertEqual(await link.power.get(), aiopjlink.Power.State.WARMING)

    async def test_connection_is_kept(self):
        """Discarding the line is not a reason to throw the connection away."""
        projector = StrayLineProjector()
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.power.turn_on()
            await asyncio.sleep(0.4)
            await link.errors.query()
            await link.power.get()
        self.assertEqual(projector.connections, 1)
        self.assertEqual(projector.lines, [b"%1POWR 1\r", b"%1ERST ?\r", b"%1POWR ?\r"])

    async def test_what_was_discarded_is_logged(self):
        """So that it can be seen what the projector sends."""
        projector = StrayLineProjector()
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.power.turn_on()
            await asyncio.sleep(0.4)
            with self.assertLogs("aiopjlink", level="DEBUG") as logs:
                await link.errors.query()
        self.assertIn("discarded unsolicited data from the projector: b'%1powr=0\\r'", "\n".join(logs.output))

    async def test_nothing_is_discarded_when_nothing_is_there(self):
        projector = StrayLineProjector()
        async with raw_tcp_server(projector) as server, server.client(timeout=TIMEOUT) as link:
            await link.errors.query()
            with self.assertLogs("aiopjlink", level="DEBUG") as logs:
                await link.errors.query()
                await link.power.get()
        self.assertNotIn("discarded", "\n".join(logs.output))
        self.assertEqual(projector.connections, 1)
