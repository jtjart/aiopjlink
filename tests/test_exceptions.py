import unittest

import aiopjlink
from aiopjlink import (
    PJLinkConnectionClosed,
    PJLinkConnectionError,
    PJLinkDeviceFailure,
    PJLinkException,
    PJLinkInvalidParameter,
    PJLinkNoConnection,
    PJLinkNotReady,
    PJLinkNotSupported,
    PJLinkPassword,
    PJLinkProjectorError,
    PJLinkProtocolError,
    PJLinkUnexpectedResponseParameter,
)
from mock_projector import mock_client_server_noauth


class HierarchyTests(unittest.TestCase):
    """The exception hierarchy is part of the public API."""

    def test_unreachable_projector_is_one_family(self):
        """Everything that means "projector not reachable or not talking" shares one base."""
        for exc in (PJLinkNoConnection, PJLinkConnectionClosed):
            self.assertTrue(issubclass(exc, PJLinkConnectionError), exc)

    def test_projector_replies_are_one_family(self):
        for exc in (PJLinkNotSupported, PJLinkInvalidParameter, PJLinkNotReady, PJLinkDeviceFailure):
            self.assertTrue(issubclass(exc, PJLinkProjectorError), exc)

    def test_families_do_not_overlap(self):
        """A projector reply is not a connection problem and not a protocol violation (and vice versa)."""
        for exc in (PJLinkNotSupported, PJLinkInvalidParameter, PJLinkNotReady, PJLinkDeviceFailure):
            self.assertFalse(issubclass(exc, (PJLinkConnectionError, PJLinkProtocolError)), exc)
        for exc in (PJLinkNoConnection, PJLinkConnectionClosed):
            self.assertFalse(issubclass(exc, (PJLinkProjectorError, PJLinkProtocolError)), exc)

    def test_everything_derives_from_the_base_exception(self):
        for exc in (
            PJLinkConnectionError,
            PJLinkNoConnection,
            PJLinkConnectionClosed,
            PJLinkPassword,
            PJLinkProtocolError,
            PJLinkUnexpectedResponseParameter,
            PJLinkProjectorError,
            PJLinkNotSupported,
            PJLinkInvalidParameter,
            PJLinkNotReady,
            PJLinkDeviceFailure,
        ):
            self.assertTrue(issubclass(exc, PJLinkException), exc)

    def test_exports(self):
        self.assertIn("PJLinkConnectionError", aiopjlink.__all__)

    def test_projector_error_carries_the_command(self):
        self.assertIsNone(PJLinkProjectorError("no signal input").command)
        self.assertEqual(PJLinkNotSupported("no lamp", command="LAMP").command, "LAMP")
        self.assertEqual(str(PJLinkNotSupported("no lamp", command="LAMP")), "no lamp")


class Err1MeaningTests(unittest.IsolatedAsyncioTestCase):
    """ERR1 is one exception class, but its message says what it means for the command that was sent."""

    async def _err1(self, command, respond, call):
        async with mock_client_server_noauth() as (server, client):
            with self.assertRaises(PJLinkNotSupported) as ctx:
                async with server.when(command, respond_with=respond):
                    await call(client)
        return ctx.exception

    async def test_specific_meanings(self):
        cases = [
            (b"%1LAMP ?\r", b"%1LAMP=ERR1\r", lambda c: c.lamps.status(), "no lamp", "LAMP"),
            (b"%2FILT ?\r", b"%2FILT=ERR1\r", lambda c: c.filter.hours(), "no filter", "FILT"),
            (b"%2SVOL 1\r", b"%2SVOL=ERR1\r", lambda c: c.speaker.turn_up(), "no speaker installed", "SVOL"),
            (b"%2SVOL 0\r", b"%2SVOL=ERR1\r", lambda c: c.speaker.turn_down(), "no speaker installed", "SVOL"),
            (b"%2MVOL 1\r", b"%2MVOL=ERR1\r", lambda c: c.microphone.turn_up(), "no microphone installed", "MVOL"),
            (b"%2FREZ 1\r", b"%2FREZ=ERR1\r", lambda c: c.freeze.set(True), "freeze not supported", "FREZ"),
            (b"%2FREZ ?\r", b"%2FREZ=ERR1\r", lambda c: c.freeze.get(), "freeze not supported", "FREZ"),
        ]
        for command, respond, call, message, name in cases:
            with self.subTest(command=command):
                err = await self._err1(command, respond, call)
                self.assertEqual(str(err), message)
                self.assertEqual(err.command, name)

    async def test_other_commands_keep_the_generic_meaning(self):
        err = await self._err1(b"%1POWR 1\r", b"%1POWR=ERR1\r", lambda c: c.power.turn_on())
        self.assertEqual(str(err), "unsupported command")
        self.assertEqual(err.command, "POWR")


class OkToQueryTests(unittest.IsolatedAsyncioTestCase):
    """A projector that answers a status query with `OK` is not ready: that is an ERR3."""

    async def test_status_queries(self):
        cases = [
            (b"%1POWR ?\r", b"%1POWR=OK\r", lambda c: c.power.get(), "POWR"),
            (b"%1INPT ?\r", b"%1INPT=OK\r", lambda c: c.sources.get(), "INPT"),
            (b"%1AVMT ?\r", b"%1AVMT=OK\r", lambda c: c.mute.status(), "AVMT"),
            (b"%1ERST ?\r", b"%1ERST=OK\r", lambda c: c.errors.query(), "ERST"),
            (b"%1LAMP ?\r", b"%1LAMP=OK\r", lambda c: c.lamps.status(), "LAMP"),
            (b"%1INST ?\r", b"%1INST=OK\r", lambda c: c.sources.available(), "INST"),
            (b"%2IRES ?\r", b"%2IRES=OK\r", lambda c: c.sources.resolution(), "IRES"),
            (b"%2RRES ?\r", b"%2RRES=OK\r", lambda c: c.sources.recommended_resolution(), "RRES"),
            (b"%2FILT ?\r", b"%2FILT=OK\r", lambda c: c.filter.hours(), "FILT"),
            (b"%2FREZ ?\r", b"%2FREZ=OK\r", lambda c: c.freeze.get(), "FREZ"),
            (b"%1CLSS ?\r", b"%1CLSS=OK\r", lambda c: c.info.pjlink_class(), "CLSS"),
        ]
        for command, respond, call, name in cases:
            with self.subTest(command=command):
                async with mock_client_server_noauth() as (server, client):
                    with self.assertRaises(PJLinkNotReady) as ctx:
                        async with server.when(command, respond_with=respond):
                            await call(client)
                self.assertEqual(ctx.exception.command, name)

    async def test_free_text_may_be_ok(self):
        """`OK` is a legitimate name, so text queries return it as it is."""
        async with mock_client_server_noauth() as (server, client):
            async with server.when(b"%1NAME ?\r", respond_with=b"%1NAME=OK\r"):
                self.assertEqual(await client.info.projector_name(), "OK")
            async with server.when(b"%2SVER ?\r", respond_with=b"%2SVER=OK\r"):
                self.assertEqual(await client.info.software_version(), "OK")

    async def test_mute_not_muted_variants(self):
        """`10` and `20` are read as "not muted", like pypjlink did."""
        async with mock_client_server_noauth() as (server, client):
            for response in (b"%1AVMT=10\r", b"%1AVMT=20\r"):
                async with server.when(b"%1AVMT ?\r", respond_with=response):
                    self.assertEqual(await client.mute.status(), (False, False))
