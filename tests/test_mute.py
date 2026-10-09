import unittest

import aiopjlink
from mock_projector import (
    NoClientMessage,
    mock_client_server_noauth,
)


class MuteGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink mute controls behave as expected."""

    async def test_status(self):
        """Mute status is acquired OK."""
        async with mock_client_server_noauth() as (server, client):
            # Video only muted.
            async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=11\r"):
                video, audio = await client.mute.status()
                self.assertEqual(video, True)
                self.assertEqual(audio, False)

            # Audio only muted.
            async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=21\r"):
                video, audio = await client.mute.status()
                self.assertEqual(video, False)
                self.assertEqual(audio, True)

            # Nothing muted.
            async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=30\r"):
                video, audio = await client.mute.status()
                self.assertEqual(video, False)
                self.assertEqual(audio, False)

            # Both audio and video muted.
            async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=31\r"):
                video, audio = await client.mute.status()
                self.assertEqual(video, True)
                self.assertEqual(audio, True)

            # Bad information from projector.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=41\r"):
                    video, audio = await client.mute.status()
            self.assertEqual(str(err.exception), "unexpected mute response")

    async def test_control_api(self):
        """Mute status can be set OK using expressive methods."""
        async with mock_client_server_noauth() as (server, client):
            # VIDEO
            # %1AVMT 11	%1AVMT=OK	blanking on
            async with server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.video(True)
            # %1AVMT 10	%1AVMT=OK	blanking off
            async with server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.video(False)

            # AUDIO
            # %1AVMT 21	%1AVMT=OK	audio muting on
            async with server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.audio(True)
            # %1AVMT 20	%1AVMT=OK	audio muting off
            async with server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.audio(False)

            # BOTH AT ONCE
            # %1AVMT 31	%1AVMT=OK	blanking on and audio muting on
            async with server.when(b"%1AVMT 31\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.both(True)

            # %1AVMT 30	%1AVMT=OK	blanking on and audio muting off
            async with server.when(b"%1AVMT 30\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.both(False)

    async def test_set(self):
        """Mute status can be set OK using the shortcut set method."""
        async with mock_client_server_noauth() as (server, client):
            # Fully specified (3x condition).
            async with server.when(b"%1AVMT 31\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(True, True)
            async with server.when(b"%1AVMT 30\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(False, False)

            # Fully specified (2x instructions)
            async with server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"):
                async with server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"):
                    await client.mute.set(True, False)

            async with server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"):
                async with server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"):
                    await client.mute.set(False, True)

            # Partially specified (for audio) (1x instruction)
            async with server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=None, audio=True)
            async with server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=None, audio=False)

            # Partially specified (for video) (1x instruction)
            async with server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=True, audio=None)
            async with server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=False, audio=None)

            # Nothing specified - so no messages sent.
            with self.assertRaises(NoClientMessage):
                async with server.when(b"%1XXXX 11\r", respond_with=b"NOTHING\r"):
                    await client.mute.set(None, None)
