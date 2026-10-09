import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class ErrorGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink error reporting behaves as expected."""

    async def test_query(self):
        """Error status parses results correctly."""
        async with mock_client_server_noauth() as (server, client):
            # No errors!
            async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=000000\r"):
                errors = await client.errors.query()
                self.assertEqual(
                    errors,
                    {
                        aiopjlink.Errors.Category.FAN: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.LAMP: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.TEMP: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.COVER: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.FILTER: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.OTHER: aiopjlink.Errors.Level.OK,
                    },
                )

            # Two warnings and one failure.
            async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=101020\r"):
                errors = await client.errors.query()
                self.assertEqual(
                    errors,
                    {
                        aiopjlink.Errors.Category.FAN: aiopjlink.Errors.Level.WARN,
                        aiopjlink.Errors.Category.LAMP: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.TEMP: aiopjlink.Errors.Level.WARN,
                        aiopjlink.Errors.Category.COVER: aiopjlink.Errors.Level.OK,
                        aiopjlink.Errors.Category.FILTER: aiopjlink.Errors.Level.ERROR,
                        aiopjlink.Errors.Category.OTHER: aiopjlink.Errors.Level.OK,
                    },
                )

            # Bad error from the projector - too many errors.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=0000000\r"):
                    errors = await client.errors.query()
            self.assertEqual(str(err.exception), "unexpected number of error types reported")

            # Bad error from the projector - unknown error type.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=003000\r"):
                    errors = await client.errors.query()
            self.assertEqual(str(err.exception), "unknown error level")
