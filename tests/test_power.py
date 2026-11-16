import unittest

import aiopjlink2
from mock_projector import mock_tcp_pjlink


class PowerGroup(unittest.IsolatedAsyncioTestCase):
    """PJLink power control behaves as expected."""

    async def test_state_enum_coercion(self) -> None:
        """Do the enums behave logically."""
        self.assertEqual(bool(aiopjlink2.Power.State.ON), True)
        self.assertEqual(bool(aiopjlink2.Power.State.OFF), False)
        self.assertTrue(aiopjlink2.Power.State.ON)
        self.assertFalse(aiopjlink2.Power.State.OFF)

        # Power status (truthy).
        self.assertTrue(aiopjlink2.Power.State.ON)
        self.assertTrue(aiopjlink2.Power.State.WARMING)

        # Power status (falsy).
        self.assertFalse(aiopjlink2.Power.State.COOLING)
        self.assertFalse(aiopjlink2.Power.State.OFF)

    async def test_power_get(self) -> None:
        """Get power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = server.client()
            self.addAsyncCleanup(client.close)

            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink2.Power.State.OFF)

            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=1\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink2.Power.State.ON)

            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=2\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink2.Power.State.COOLING)

            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=3\r"):
                status = await client.power.get()
                self.assertEqual(status, aiopjlink2.Power.State.WARMING)

            # Unexpected power result.
            with self.assertRaises(aiopjlink2.PJLinkUnexpectedValueError) as err:
                async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=A\r"):
                    await client.power.get()
            self.assertEqual(str(err.exception), "unexpected power state")

    async def test_power_set(self) -> None:
        """Set power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = server.client()
            self.addAsyncCleanup(client.close)

            async with server.when(b"%1POWR 1\r", respond_with=b"%1POWR=OK\r"):
                await client.power.set(aiopjlink2.Power.State.ON)

            async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                await client.power.set(aiopjlink2.Power.State.OFF)

            async with server.when(b"%2POWR 1\r", respond_with=b"%2POWR=OK\r"):
                await client.power.set(aiopjlink2.Power.State.ON, pjclass=aiopjlink2.PJClass.TWO)

            async with server.when(b"%2POWR 0\r", respond_with=b"%2POWR=OK\r"):
                await client.power.set(aiopjlink2.Power.State.OFF, pjclass=aiopjlink2.PJClass.TWO)

            # Power set unavailable (test duplicated in test_response_parsing)
            with self.assertRaises(aiopjlink2.PJLinkNotReadyError) as err_not_ready:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=ERR3\r"):
                    await client.power.set(client.power.State.OFF)
            self.assertEqual(str(err_not_ready.exception), "unavailable in the current state")

            # Power set not possible (test duplicated in test_response_parsing)
            with self.assertRaises(aiopjlink2.PJLinkMalfunctionError) as err_device_failure:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=ERR4\r"):
                    await client.power.set(client.power.State.OFF)
            self.assertEqual(str(err_device_failure.exception), "projector or display failure")

            # Unexpected projector reply to a sensible message.
            with self.assertRaises(aiopjlink2.PJLinkUnexpectedValueError) as err_unexpected_response_parameter:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=UGH\r"):
                    await client.power.set(aiopjlink2.Power.State.OFF)
            self.assertEqual(str(err_unexpected_response_parameter.exception), "expected OK response")

            # Only `ON` and `OFF` can be set.
            with self.assertRaises(ValueError) as err_value_error:
                async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                    await client.power.set(aiopjlink2.Power.State.COOLING)
            self.assertEqual(str(err_value_error.exception), "expected Power.State.ON or Power.State.OFF")

    async def test_power_shortcuts(self) -> None:
        """Set power status."""

        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = server.client()
            self.addAsyncCleanup(client.close)

            async with server.when(b"%1POWR 1\r", respond_with=b"%1POWR=OK\r"):
                await client.power.turn_on()

            async with server.when(b"%1POWR 0\r", respond_with=b"%1POWR=OK\r"):
                await client.power.turn_off()
