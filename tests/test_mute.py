import unittest

import aiopjlink2
from mock_projector import (
    NoClientMessageError,
    mock_client_server_noauth,
)


class MuteGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink mute controls behave as expected."""

    async def test_status(self) -> None:
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
            with self.assertRaises(aiopjlink2.PJLinkUnexpectedValueError) as err:
                async with server.when(b"%1AVMT ?\r", respond_with=b"%1AVMT=41\r"):
                    video, audio = await client.mute.status()
            self.assertEqual(str(err.exception), "unexpected mute response")

    @staticmethod
    async def test_control_api() -> None:
        """Mute status can be set OK using expressive methods."""
        async with mock_client_server_noauth() as (server, client):
            async with server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.video(True)
            async with server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.video(False)

            async with server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.audio(True)
            async with server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.audio(False)

            async with server.when(b"%1AVMT 31\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.both(True)

            async with server.when(b"%1AVMT 30\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.both(False)

    async def test_set(self) -> None:
        """Mute status can be set OK using the shortcut set method."""
        async with mock_client_server_noauth() as (server, client):
            # The same setting for both tracks takes one command.
            async with server.when(b"%1AVMT 31\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(True, True)
            async with server.when(b"%1AVMT 30\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(False, False)

            # Different settings take one command per track.
            async with (
                server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"),
                server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"),
            ):
                await client.mute.set(True, False)

            async with (
                server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"),
                server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"),
            ):
                await client.mute.set(False, True)

            # A single track takes one command.
            async with server.when(b"%1AVMT 21\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=None, audio=True)
            async with server.when(b"%1AVMT 20\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=None, audio=False)

            async with server.when(b"%1AVMT 11\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=True, audio=None)
            async with server.when(b"%1AVMT 10\r", respond_with=b"%1AVMT=OK\r"):
                await client.mute.set(video=False, audio=None)

            # Nothing to change: nothing is sent.
            with self.assertRaises(NoClientMessageError):
                async with server.when(b"%1XXXX 11\r", respond_with=b"NOTHING\r"):
                    await client.mute.set(None, None)
