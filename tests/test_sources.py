import unittest

import aiopjlink
from mock_projector import mock_client_server_noauth


class SourcesGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink input source control and enumeration behaves as expected."""

    async def test_enum(self):
        """Ensure the enumeration matches the spec."""
        self.assertEqual(aiopjlink.Sources.Mode.RGB.value, "1")
        self.assertEqual(aiopjlink.Sources.Mode.VIDEO.value, "2")
        self.assertEqual(aiopjlink.Sources.Mode.DIGITAL.value, "3")
        self.assertEqual(aiopjlink.Sources.Mode.STORAGE.value, "4")
        self.assertEqual(aiopjlink.Sources.Mode.NETWORK.value, "5")
        self.assertEqual(aiopjlink.Sources.Mode.INTERNAL.value, "6")

    async def test_inpt(self):
        """Check the INPT instructions work."""
        async with mock_client_server_noauth() as (server, client):
            # Get current source.
            async with server.when(b"%1INPT ?\r", respond_with=b"%1INPT=31\r"):
                mode, index = await client.sources.get()
                self.assertEqual(mode, client.sources.Mode.DIGITAL)
                self.assertEqual(index, "1")

            # Set current source.
            async with server.when(b"%1INPT 21\r", respond_with=b"%1INPT=OK\r"):
                await client.sources.set(aiopjlink.Sources.Mode.VIDEO, "1")

            # Bad response: wrong length.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1INPT ?\r", respond_with=b"%1INPT=311\r"):
                    await client.sources.get()
            self.assertEqual(str(err.exception), "expected 2 INPT response characters")

            # Bad response: unknown input mode.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1INPT ?\r", respond_with=b"%1INPT=91\r"):
                    await client.sources.get()
            self.assertEqual(str(err.exception), "unexpected input source mode")

    async def test_inst_class1(self):
        """Test that available sources can be enumerated."""
        async with mock_client_server_noauth() as (server, client):
            # List available clients
            async with server.when(b"%1INST ?\r", respond_with=b"%1INST=11 31 32 41 52 56\r"):
                sources = await client.sources.available()

                # Length
                self.assertEqual(len(sources), 6)

                # RGB 1
                mode, index = sources[0]
                self.assertEqual(mode, aiopjlink.Sources.Mode.RGB)
                self.assertEqual(index, "1")

                # DIGITAL 1
                mode, index = sources[1]
                self.assertEqual(mode, aiopjlink.Sources.Mode.DIGITAL)
                self.assertEqual(index, "1")

                # DIGITAL 2
                mode, index = sources[2]
                self.assertEqual(mode, aiopjlink.Sources.Mode.DIGITAL)
                self.assertEqual(index, "2")

                # STORAGE 1
                mode, index = sources[3]
                self.assertEqual(mode, aiopjlink.Sources.Mode.STORAGE)
                self.assertEqual(index, "1")

                # NETWORK 2
                mode, index = sources[4]
                self.assertEqual(mode, aiopjlink.Sources.Mode.NETWORK)
                self.assertEqual(index, "2")

                # NETWORK 6
                mode, index = sources[5]
                self.assertEqual(mode, aiopjlink.Sources.Mode.NETWORK)
                self.assertEqual(index, "6")

            # Unparsable list from the projector.
            for response in (b"%1INST=\r", b"%1INST=91\r", b"%1INST=111\r"):
                with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                    async with server.when(b"%1INST ?\r", respond_with=response):
                        await client.sources.available()
                self.assertEqual(str(err.exception), "unable to parse available sources")

    async def test_inst_innm_class2(self):
        """Test that available sources and their names can be enumerated."""
        async with mock_client_server_noauth() as (server, client):
            # List available clients (Class 2) - brief as the Class 1 shares the logic.
            async with server.when(b"%2INST ?\r", respond_with=b"%2INST=11 31 32 41 52 56\r"):
                sources = await client.sources.available(pjclass=aiopjlink.PJClass.TWO)
                self.assertEqual(len(sources), 6)

            # Get the names of a display source (values taken from actual projector output).
            async with server.when(b"%2INNM ?31\r", respond_with=b"%2INNM=DVI-D\r"):
                name = await client.sources.get_source_name(aiopjlink.Sources.Mode.DIGITAL, "1")
                self.assertEqual(name, "DVI-D")

            # Accept integers (because we are liberal in what we accept).
            async with server.when(b"%2INNM ?31\r", respond_with=b"%2INNM=DVI-D\r"):
                name = await client.sources.get_source_name(aiopjlink.Sources.Mode.DIGITAL, 1)
                self.assertEqual(name, "DVI-D")

            # Integers above 9 are converted to letters: 11 is "B".
            async with server.when(b"%2INNM ?3B\r", respond_with=b"%2INNM=HDMI\r"):
                name = await client.sources.get_source_name(aiopjlink.Sources.Mode.DIGITAL, 11)
                self.assertEqual(name, "HDMI")

            # Reject invalid indexes (before hitting the server).
            for bad_index in ("11", 0, 36):
                with self.assertRaises(ValueError):
                    await client.sources.get_source_name(aiopjlink.Sources.Mode.DIGITAL, bad_index)

            # Get the names of available.
            async with server.when(b"%2INST ?\r", respond_with=b"%2INST=11\r"):
                async with server.when(b"%2INNM ?11\r", respond_with=b"%2INNM=Computer\r"):
                    sources = await client.sources.available_with_names()
                    self.assertEqual(len(sources), 1)
                    mode, index, name = sources[0]
                    self.assertEqual(mode, aiopjlink.Sources.Mode.RGB)
                    self.assertEqual(index, "1")
                    self.assertEqual(name, "Computer")

    async def test_inpt_index_forms(self):
        """Setting a source accepts digits, letters (any case) and integers."""
        async with mock_client_server_noauth() as (server, client):
            mode = aiopjlink.Sources.Mode.VIDEO

            # Digit as string and as int.
            async with server.when(b"%1INPT 21\r", respond_with=b"%1INPT=OK\r"):
                await client.sources.set(mode, "1")
            async with server.when(b"%1INPT 21\r", respond_with=b"%1INPT=OK\r"):
                await client.sources.set(mode, 1)

            # Lower case is converted to upper case (Class 2 sources).
            async with server.when(b"%2INPT 2A\r", respond_with=b"%2INPT=OK\r"):
                await client.sources.set(mode, "a", pjclass=aiopjlink.PJClass.TWO)

            # Integers above 9 are converted to letters.
            async with server.when(b"%2INPT 2B\r", respond_with=b"%2INPT=OK\r"):
                await client.sources.set(mode, 11, pjclass=aiopjlink.PJClass.TWO)

            # Invalid indexes are rejected before anything is sent.
            with self.assertRaises(ValueError):
                await client.sources.set(mode, "11")
            with self.assertRaises(ValueError):
                await client.sources.set(mode, 0)

    async def test_ires(self):
        """Test that the resolution of the current input can be recieved."""
        async with mock_client_server_noauth() as (server, client):
            # Get resolution.
            async with server.when(b"%2IRES ?\r", respond_with=b"%2IRES=100x200\r"):
                x, y = await client.sources.resolution()
                self.assertEqual(x, 100)
                self.assertEqual(y, 200)

            # Handle spec edge cases.
            with self.assertRaises(aiopjlink.PJLinkProjectorError) as err:
                async with server.when(b"%2IRES ?\r", respond_with=b"%2IRES=-\r"):
                    await client.sources.resolution()
            self.assertEqual(str(err.exception), "no signal input")

            # Handle spec edge cases.
            with self.assertRaises(aiopjlink.PJLinkProjectorError) as err:
                async with server.when(b"%2IRES ?\r", respond_with=b"%2IRES=*\r"):
                    await client.sources.resolution()
            self.assertEqual(str(err.exception), "unknown signal")

            # Bad response from the projecetor.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2IRES ?\r", respond_with=b"%2IRES=\r"):
                    x, y = await client.sources.resolution()
            self.assertEqual(str(err.exception), "unable to parse resolution")

    async def test_rres(self):
        """Test that the recommended resolution for the current input can be recieved."""
        async with mock_client_server_noauth() as (server, client):
            # Get resolution.
            async with server.when(b"%2RRES ?\r", respond_with=b"%2RRES=1920x1080\r"):
                x, y = await client.sources.recommended_resolution()
                self.assertEqual(x, 1920)
                self.assertEqual(y, 1080)

            # Bad response from the projecetor.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%2RRES ?\r", respond_with=b"%2RRES=\r"):
                    x, y = await client.sources.recommended_resolution()
            self.assertEqual(str(err.exception), "unable to parse resolution")
