import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class FreezeGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink freeze behavour activates and reports correctly."""

    async def test_set(self):
        """Screen freezes and unfreezes."""
        async with mock_client_server_noauth() as (server, client):
            # Expected.
            async with server.when(b"%2FREZ 1\r", respond_with=b"%2FREZ=OK\r"):
                await client.freeze.set(True)
            async with server.when(b"%2FREZ 0\r", respond_with=b"%2FREZ=OK\r"):
                await client.freeze.set(False)

            # Unexpected.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2FREZ 1\r", respond_with=b"%2FREZ=UGH\r"):
                    await client.freeze.set(True)
            self.assertEqual(str(err.exception), "expected OK response")

    async def test_get(self):
        """Getting the current freeze state."""
        async with mock_client_server_noauth() as (server, client):
            # Expected.
            async with server.when(b"%2FREZ ?\r", respond_with=b"%2FREZ=0\r"):
                self.assertEqual(await client.freeze.get(), False)
            async with server.when(b"%2FREZ ?\r", respond_with=b"%2FREZ=1\r"):
                self.assertEqual(await client.freeze.get(), True)

            # Unexpected.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2FREZ ?\r", respond_with=b"%2FREZ=2\r"):
                    await client.freeze.get()
            self.assertEqual(str(err.exception), "unexpected freeze state")
