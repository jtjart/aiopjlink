import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class FilterGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink filter reports correctly."""

    async def test_hours(self):
        """Get the correct filter hours."""
        async with mock_client_server_noauth() as (server, client):
            # Valid filter.
            async with server.when(b"%2FILT ?\r", respond_with=b"%2FILT=100\r"):
                hours = await client.filter.hours()
                self.assertEqual(hours, 100)

            # No filter handled correctly.
            with self.assertRaises(aiopjlink.PJLinkNotSupported) as err:
                async with server.when(b"%2FILT ?\r", respond_with=b"%2FILT=ERR1\r"):
                    hours = await client.filter.hours()
            self.assertEqual(str(err.exception), "no filter")

            # Unparsable usage time.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2FILT ?\r", respond_with=b"%2FILT=abc\r"):
                    hours = await client.filter.hours()
            self.assertEqual(str(err.exception), "filter usage not parsable")

    async def test_replacement_model(self):
        """Get a list of replacement filter models."""
        async with mock_client_server_noauth() as (server, client):
            # Once replacement.
            async with server.when(b"%2RFIL ?\r", respond_with=b"%2RFIL=SampleFilter\r"):
                models = await client.filter.replacement_models()
                self.assertEqual(len(models), 1)
                self.assertEqual(models[0], "SampleFilter")

            # Two replacements.
            async with server.when(b"%2RFIL ?\r", respond_with=b"%2RFIL=SampleFilter ELPAF46\r"):
                models = await client.filter.replacement_models()
                self.assertEqual(len(models), 2)
                self.assertEqual(models[0], "SampleFilter")
                self.assertEqual(models[1], "ELPAF46")

            # No replacements.
            async with server.when(b"%2RFIL ?\r", respond_with=b"%2RFIL=\r"):
                models = await client.filter.replacement_models()
                self.assertEqual(len(models), 0)
