import asyncio
import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


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
