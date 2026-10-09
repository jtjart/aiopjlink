import hashlib
import unittest

import aiopjlink
from mock_projector import (
    NoClientMessage,
    UnexpectedClientMessage,
    mock_client_server_noauth,
    mock_tcp_pjlink,
)


class ReflectiveMockTests(unittest.IsolatedAsyncioTestCase):
    """Validate the test case framework."""

    async def test_mock_nonresponse(self):
        """
        The test framework notices that the client has not issued the expected command.
        It times out with a `NoClientMessage` and closes the server.
        """
        # Start server with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")

            # Expect a POWR status request.
            with self.assertRaises(NoClientMessage):
                async with server.when("%1POWR ?", respond_with=b"%1POWR=0\r"):
                    # Never give one.
                    pass

    async def test_mock_unexpectedresponse(self):
        """
        The test framework notices that the client has issued an "incorrect" command
        to the one that was expected (in this case, during auth).
        It catches this error, closes the server, and issues an `UnexpectedClientMessage`.

        This helps us check the tests are written correctly without super complex error messages.
        """
        # Start server with auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 1 21d0e96e\r")

            # Expect an unexpected message (valid test behaviour).
            with self.assertRaises(UnexpectedClientMessage):
                # Compute what the projector expects to see if the password was actually "ABC123"
                # with the above salt token (21d0e96e).
                salted_password = hashlib.md5(b"21d0e96eABC123").hexdigest().encode()
                expected_cmd = bytes(salted_password) + b"%1POWR ?\r"

                # Tell the test framework to raise an UnexpectedClientMessage
                # if we get a different password sent from the client.  In this case, that is
                # what we want (not an auth error) because we are testing our ability to mock
                # a projector and NOT the behaviour of the projector.
                async with server.when(expected_cmd, respond_with=b"%1POWR=0\r"):
                    # Give a junk password to trigger the UnexpectedClientMessage.
                    link = aiopjlink.PJLink(address="127.0.0.1", password="INCORRECT")
                    await link.power.get()

    async def test_mock_unexpectedresponse_after_connection(self):
        """
        The test framework allows: (1) successful messages to be handled OK, (2) successive
        successful messages, and (3) catches errors in successive unexpected messages.

        This ensures the test framework is suitable for multiple calls (e.g. internal buffers
        are reset, and that sort of thing).
        """
        # Open a connection successfully with no auth.
        async with mock_tcp_pjlink() as server:
            server.open_and_send(b"PJLINK 0\r")
            client = aiopjlink.PJLink(address="127.0.0.1", password=None)

            # Check that the test framework recieves the expected message.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                value = await client.transmit("POWR", "?", pjclass=aiopjlink.PJClass.ONE)
                self.assertEqual(value, "0")

            # Check that the test framework recieves the expected message - 2nd time.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                value = await client.transmit("POWR", "?", pjclass=aiopjlink.PJClass.ONE)
                self.assertEqual(value, "0")

            # Check that the test framework handles the mistake in the test code.
            with self.assertRaises(UnexpectedClientMessage):
                async with server.when(b"SOME_MESSAGE\r", respond_with=b"%1POWR=0\r"):
                    await client.transmit("POWR", "?", pjclass=aiopjlink.PJClass.ONE)

    async def test_mock_response_stacking(self):
        """The test framework allows expected responses to be queued."""
        # Open a connection successfully with no auth.
        async with mock_client_server_noauth() as (server, client):
            # Expect a POWR followed by a CLSS.
            async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=2\r"):
                    value = await client.transmit("POWR", "?", pjclass=aiopjlink.PJClass.ONE)
                    self.assertEqual(value, "0")
                    value = await client.transmit("CLSS", "?", pjclass=aiopjlink.PJClass.ONE)
                    self.assertEqual(value, "2")

            # Expect a POWR followed by a CLSS - but don't get it, so we should
            # expect a warning about the test case: UnexpectedClientMessage
            with self.assertRaises(UnexpectedClientMessage):
                async with server.when(b"%1POWR ?\r", respond_with=b"%1POWR=0\r"):
                    async with server.when(b"%1CLSS ?\r", respond_with=b"%1CLSS=2\r"):
                        await client.transmit("CLSS", "?", pjclass=aiopjlink.PJClass.ONE)
                        await client.transmit("POWR", "?", pjclass=aiopjlink.PJClass.ONE)
