import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class LampGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink lamps report correctly."""

    async def test_status(self):
        """Lamp status parses correctly for common values."""
        async with mock_client_server_noauth() as (server, client):
            # Two lamps (from PJLink test excel sheet)
            async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=8253 1 13442 1\r"):
                lamps = await client.lamps.status()
                self.assertEqual(len(lamps), 2)

                hours, state = lamps[0]
                self.assertEqual(hours, 8253)
                self.assertEqual(state, aiopjlink.Lamp.State.ON)

                hours, state = lamps[1]
                self.assertEqual(hours, 13442)
                self.assertEqual(state, aiopjlink.Lamp.State.ON)

            # One lamp off
            async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=8253 0\r"):
                lamps = await client.lamps.status()
                self.assertEqual(len(lamps), 1)
                hours, state = lamps[0]
                self.assertEqual(hours, 8253)
                self.assertEqual(state, aiopjlink.Lamp.State.OFF)

            # No lamps in the projector.
            with self.assertRaises(aiopjlink.PJLinkNotSupported):
                async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=ERR1\r"):
                    lamps = await client.lamps.status()

            # Unparsable feedback from projector.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=1 0 10\r"):
                    lamps = await client.lamps.status()
            self.assertEqual(str(err.exception), "unparsable lamp status")

            # Bad feedback from the projector.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=\r"):
                    lamps = await client.lamps.status()
            self.assertEqual(str(err.exception), "unparsable lamp status")

            # Bad feedback from the projector.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=100 3\r"):
                    lamps = await client.lamps.status()
            self.assertEqual(str(err.exception), "unparsable lamp status")

    async def test_hours(self):
        """The hours accelerator gets the correct lamp hours."""
        async with mock_client_server_noauth() as (server, client):
            # Two lamps (from PJLink test excel sheet)
            async with server.when(b"%1LAMP ?\r", respond_with=b"%1LAMP=8253 1 13442 1\r"):
                hours = await client.lamps.hours()
                self.assertEqual(hours, 8253)

    async def test_replacement_model(self):
        """Get a list of replacement lamp models."""
        async with mock_client_server_noauth() as (server, client):
            # Once replacement.
            async with server.when(b"%2RLMP ?\r", respond_with=b"%2RLMP=SampleLamp\r"):
                models = await client.lamps.replacement_models()
                self.assertEqual(len(models), 1)
                self.assertEqual(models[0], "SampleLamp")

            # Two replacements.
            async with server.when(b"%2RLMP ?\r", respond_with=b"%2RLMP=SampleLamp RC11\r"):
                models = await client.lamps.replacement_models()
                self.assertEqual(len(models), 2)
                self.assertEqual(models[0], "SampleLamp")
                self.assertEqual(models[1], "RC11")

            # No replacements.
            async with server.when(b"%2RLMP ?\r", respond_with=b"%2RLMP=\r"):
                models = await client.lamps.replacement_models()
                self.assertEqual(len(models), 0)
