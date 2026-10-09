import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class VolumeGroups(unittest.IsolatedAsyncioTestCase):
    """PJLink volume increments and decrements correctly."""

    async def test_change_volume(self):
        """Volume turns up and down for speaker and microphone."""
        async with mock_client_server_noauth() as (server, client):
            # Turn up mic.
            async with server.when(b"%2MVOL 1\r", respond_with=b"%2MVOL=OK\r"):
                await client.microphone.turn_up()

            # Turn up speaker.
            async with server.when(b"%2SVOL 1\r", respond_with=b"%2SVOL=OK\r"):
                await client.speaker.turn_up()

            # Turn down mic.
            async with server.when(b"%2MVOL 0\r", respond_with=b"%2MVOL=OK\r"):
                await client.microphone.turn_down()

            # Turn down speaker.
            async with server.when(b"%2SVOL 0\r", respond_with=b"%2SVOL=OK\r"):
                await client.speaker.turn_down()

            # Unexpected.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2SVOL 1\r", respond_with=b"%2SVOL=2\r"):
                    await client.speaker.turn_up()
            self.assertEqual(str(err.exception), "expected OK response")
