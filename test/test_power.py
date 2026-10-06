import unittest

import aiopjlink
from mock_projector import mock_tcp_pjlink


class PowerGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink power control behaves as expected."""

    async def test_state_enum_coercion(self):
        """Do the enums behave logically."""
        # Power commands.
        self.assertEqual(bool(aiopjlink.Power.ON), True)
        self.assertEqual(bool(aiopjlink.Power.OFF), False)
        self.assertTrue(aiopjlink.Power.ON)
        self.assertFalse(aiopjlink.Power.OFF)

        # Power status (truthy).
        self.assertTrue(aiopjlink.Power.State.ON)
        self.assertTrue(aiopjlink.Power.State.WARMING)

        # Power status (falsy).
        self.assertFalse(aiopjlink.Power.State.COOLING)
        self.assertFalse(aiopjlink.Power.State.OFF)

    async def test_power_get(self):
        """Get power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None)

            # Power off.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink.Power.OFF)

            # Power on.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=1\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink.Power.ON)

            # Power cooling.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=2\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink.Power.State.COOLING)

            # Power warming.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=3\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink.Power.State.WARMING)

            # Unxpected power result.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=A\r"):
                    await client.power.get()
            self.assertEqual(str(err.exception), "unexpected power state")

    async def test_power_set(self):
        """Set power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None)

            # Power ON
            async with server.when(b"%1POWR 1\r", respond_with=b"%1POWR=OK\r"):
                await client.power.set(aiopjlink.Power.ON)

            # Power OFF
            async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                await client.power.set(aiopjlink.Power.OFF)

            # Power ON
            async with server.when(b"%2POWR 1\r", respond_with=b"%2POWR=OK\r"):
                await client.power.set(aiopjlink.Power.ON, pjclass=aiopjlink.PJLink.C2)

            # Power OFF
            async with server.when(b"%2POWR 0\r", respond_with=b"%2POWR=OK\r"):
                await client.power.set(aiopjlink.Power.OFF, pjclass=aiopjlink.PJLink.C2)

            # Power set out of parameter (test duplicated in test_response_parsing)
            with self.assertRaises(aiopjlink.PJLinkERR2) as err:
                async with server.when(b"%1POWR 3\r", respond_with=b"%1POWR=ERR2\r"):
                    await client.transmit("POWR", "3", pjclass=aiopjlink.PJLink.C1)
            self.assertEqual(str(err.exception), "out of parameter")

            # Power set unavailable (test duplicated in test_response_parsing)
            with self.assertRaises(aiopjlink.PJLinkERR3) as err:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=ERR3\r"):
                    await client.power.set(client.power.OFF)
            self.assertEqual(str(err.exception), "unavailable in the current state")

            # Power set not possible (test duplicated in test_response_parsing)
            with self.assertRaises(aiopjlink.PJLinkERR4) as err:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=ERR4\r"):
                    await client.power.set(client.power.OFF)
            self.assertEqual(str(err.exception), "projector or display failure")

            # Unexpected projector reply to a sensible message.
            with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=UGH\r"):
                    await client.power.set(aiopjlink.Power.OFF)
            self.assertEqual(str(err.exception), "expected OK response")

            # Expect enums.
            with self.assertRaises(ValueError) as err:
                async with server.when(b"%1POWR 1\r", respond_with=b"%1POWR=OK\r"):
                    await client.power.set(True)
            self.assertEqual(str(err.exception), "True is not a valid Power.State")

            with self.assertRaises(ValueError) as err:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                    await client.power.set("off")
            self.assertEqual(str(err.exception), "'off' is not a valid Power.State")

            with self.assertRaises(ValueError) as err:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                    await client.power.set(aiopjlink.Power.State.COOLING)
            self.assertEqual(str(err.exception), "expected Power.State.ON or Power.State.OFF")

            # Accept PJLink strings as enum values.
            async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                await client.power.set("0")

    async def test_power_shortcuts(self):
        """Set power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None)

            # Power ON
            async with server.when(b"%1POWR 1\r", respond_with=b"%1POWR=OK\r"):
                await client.power.turn_on()

            # Power OFF
            async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                await client.power.turn_off()
