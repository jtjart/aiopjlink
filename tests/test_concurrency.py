import asyncio
import time
import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth, raw_tcp_server, until_hung_up


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    """One `PJLink` object can be shared between tasks."""

    async def test_concurrent_commands_are_serialised(self):
        """Two commands issued at the same time use one connection after the other."""
        async with mock_client_server_noauth() as (server, client):
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=1\r"):
                async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=2\r"):
                    power, pjclass = await asyncio.gather(
                        client.power.get(),
                        client.info.pjlink_class(),
                    )
            self.assertEqual(power, aiopjlink.Power.State.ON)
            self.assertEqual(pjclass, aiopjlink.PJClass.TWO)

    async def test_lock_released_after_error(self):
        """A failed command does not block the commands that follow it."""
        async with mock_client_server_noauth() as (server, client):
            # First command fails (projector reports ERR3).
            with self.assertRaises(aiopjlink.PJLinkNotReady):
                async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=ERR3\r"):
                    await client.power.get()

            # The next one still works.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                self.assertEqual(await client.power.get(), aiopjlink.Power.State.OFF)

    async def test_lock_released_after_deadline(self):
        """A command that hits the deadline does not hold up the one queued behind it."""
        timeout = 0.3

        async def silent(reader, writer):
            await until_hung_up(reader, writer)

        async with raw_tcp_server(silent):
            client = aiopjlink.PJLink(address="127.0.0.1", password=None, timeout=timeout)
            start = time.monotonic()
            results = await asyncio.gather(client.power.get(), client.power.get(), return_exceptions=True)
            elapsed = time.monotonic() - start

        self.assertTrue(all(isinstance(r, aiopjlink.PJLinkException) for r in results), results)
        self.assertGreaterEqual(elapsed, timeout * 2 * 0.9)  # One after the other.
        self.assertLess(elapsed, timeout * 2 + 1)  # One deadline each.
