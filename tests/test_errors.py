import unittest

import aiopjlink2
from mock_projector import mock_client_server_noauth


class ErrorGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink error reporting behaves as expected."""

    async def test_query(self) -> None:
        """Error status parses results correctly."""
        async with mock_client_server_noauth() as (server, client):
            # No errors!
            async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=000000\r"):
                errors = await client.errors.query()
                self.assertEqual(
                    errors,
                    {
                        aiopjlink2.Errors.Category.FAN: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.LAMP: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.TEMP: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.COVER: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.FILTER: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.OTHER: aiopjlink2.Errors.Level.OK,
                    },
                )

            # Two warnings and one failure.
            async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=101020\r"):
                errors = await client.errors.query()
                self.assertEqual(
                    errors,
                    {
                        aiopjlink2.Errors.Category.FAN: aiopjlink2.Errors.Level.WARN,
                        aiopjlink2.Errors.Category.LAMP: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.TEMP: aiopjlink2.Errors.Level.WARN,
                        aiopjlink2.Errors.Category.COVER: aiopjlink2.Errors.Level.OK,
                        aiopjlink2.Errors.Category.FILTER: aiopjlink2.Errors.Level.ERROR,
                        aiopjlink2.Errors.Category.OTHER: aiopjlink2.Errors.Level.OK,
                    },
                )

            # Bad error from the projector - too many errors.
            with self.assertRaises(aiopjlink2.PJLinkUnexpectedValueError) as err:
                async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=0000000\r"):
                    errors = await client.errors.query()
            self.assertEqual(str(err.exception), "unexpected number of error types reported")

            # Bad error from the projector - unknown error type.
            with self.assertRaises(aiopjlink2.PJLinkUnexpectedValueError) as err:
                async with server.when(b"%1ERST ?\r", respond_with=b"%1ERST=003000\r"):
                    errors = await client.errors.query()
            self.assertEqual(str(err.exception), "unknown error level")
