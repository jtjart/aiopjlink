import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class InfoGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink projector information queries."""

    async def test_software_version(self):
        """Get the software version number string."""
        async with mock_client_server_noauth() as (server, client):
            # Version provided.
            async with server.when(b"%2SVER ?\r", respond_with=b"%2SVER=24011273HQWWV105\r"):
                version = await client.info.software_version()
                self.assertEqual(version, "24011273HQWWV105")

            # No version provided.
            async with server.when(b"%2SVER ?\r", respond_with=b"%2SVER=\r"):
                version = await client.info.software_version()
                self.assertEqual(version, "")

    async def test_serial_number(self):
        """Get the device serial number string."""
        async with mock_client_server_noauth() as (server, client):
            # Version provided.
            async with server.when(b"%2SNUM ?\r", respond_with=b"%2SNUM=XA3C2400119\r"):
                version = await client.info.serial_number()
                self.assertEqual(version, "XA3C2400119")

            # No version provided.
            async with server.when(b"%2SNUM ?\r", respond_with=b"%2SNUM=\r"):
                version = await client.info.serial_number()
                self.assertEqual(version, "")

    async def test_pjlink_class(self):
        """Query the PJLink class support."""
        async with mock_client_server_noauth() as (server, client):
            # Class 1 query (default).
            async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=1\r"):
                self.assertEqual(await client.info.pjlink_class(), aiopjlink.PJClass.ONE)

            # Class 2 support from class 1 query (default).
            async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=2\r"):
                self.assertEqual(await client.info.pjlink_class(), aiopjlink.PJClass.TWO)

            # Class 2 support from class 2 query (default).
            async with server.when(b"%2CLSS ?\r", respond_with=b"%2CLSS=2\r"):
                response = await client.info.pjlink_class(pjclass=aiopjlink.PJClass.TWO)
                self.assertEqual(response, aiopjlink.PJClass.TWO)

            # Unexpected class.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=9\r"):
                    await client.info.pjlink_class()
            self.assertEqual(str(err.exception), "unexpected PJLink class")

    async def test_info_other(self):
        """Query the "other" info."""
        async with mock_client_server_noauth() as (server, client):
            # Test from spec excel sheet.
            async with server.when(b"%1INFO ?\r", respond_with=b"%1INFO=PJLink\r"):
                self.assertEqual(await client.info.other(), "PJLink")

            # Test actual projector response.
            async with server.when(b"%1INFO ?\r", respond_with=b"%1INFO=105.105.---\r"):
                self.assertEqual(await client.info.other(), "105.105.---")

            # Test no extra info.
            async with server.when(b"%1INFO ?\r", respond_with=b"%1INFO=\r"):
                self.assertEqual(await client.info.other(), "")

    async def test_product_name(self):
        """Query the product name information."""
        async with mock_client_server_noauth() as (server, client):
            # Test from actual projector.
            async with server.when(b"%1INF2 ?\r", respond_with=b"%1INF2=EPSON PU1007B/PU1007W\r"):
                self.assertEqual(await client.info.product_name(), "EPSON PU1007B/PU1007W")

            # Test no extra info.
            async with server.when(b"%1INF2 ?\r", respond_with=b"%1INF2=\r"):
                self.assertEqual(await client.info.product_name(), "")

    async def test_manufacturer_name(self):
        """Query the manufacturer name information."""
        async with mock_client_server_noauth() as (server, client):
            # Test from actual projector.
            async with server.when(b"%1INF1 ?\r", respond_with=b"%1INF1=EPSON\r"):
                self.assertEqual(await client.info.manufacturer_name(), "EPSON")

            # Test no extra info.
            async with server.when(b"%1INF1 ?\r", respond_with=b"%1INF1=\r"):
                self.assertEqual(await client.info.manufacturer_name(), "")

    async def test_projector_name(self):
        """Query the projector name information."""
        async with mock_client_server_noauth() as (server, client):
            # Test from actual projector.
            async with server.when(b"%1NAME ?\r", respond_with=b"%1NAME=EBB13648\r"):
                self.assertEqual(await client.info.projector_name(), "EBB13648")

            # Test no extra info.
            async with server.when(b"%1NAME ?\r", respond_with=b"%1NAME=\r"):
                self.assertEqual(await client.info.projector_name(), "")
