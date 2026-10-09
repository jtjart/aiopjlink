"""A mock PJLink projector for the tests.

Provides a full socket stack so the client can be tested against a projector,
including erroneous behaviour. See `PJLinkServerProtocol.when`.
"""

import asyncio
import contextlib

import aiopjlink


class PJLinkTestFrameworkError(Exception):
    """Base exception for problems with the test framework."""


class NoClientMessage(PJLinkTestFrameworkError):
    """The test case fails because the test case didn't send a client message."""


class UnexpectedClientMessage(PJLinkTestFrameworkError):
    """The test case fails because the test case expected something the client didn't send."""


class NoExpectations(PJLinkTestFrameworkError):
    """The test case fails because the mock projector recieves a command before it is told how to respond."""


class PJLinkServerProtocol(asyncio.Protocol):
    """
    Provides a method for mocking a projector, including a full socket
    stack to provide a proper simulation of a projector for the client - including
    erroneous behaviours.

    This class has some nuance - check it here.
    https://docs.python.org/3/library/asyncio-protocol.html
    """

    def __init__(self, loop, debug=False):

        # Event loop of the current test case.
        self.loop = loop

        # Should send and recieve messages be printed.
        self.debug = debug

        # An opening message is sent as soon as a connection is established.
        self._opening_message = None

        # What the projector should expect to recieve / do next (as defined by the test case).
        self._expected_events = []

        # Buffer fore incoming messages until \r.
        self._recv_buffer = b""

    def _write(self, data):
        """Send data to the client."""
        if self.debug:
            print("PJLinkServerProtocol SEND:", data)
        self.transport.write(data)

    def connection_made(self, transport):
        """Called when a connection is first made to this projector."""
        self.transport = transport
        if self.debug:
            peer = self.transport.get_extra_info("peername")
            print("PJLinkServerProtocol CONNECTION_MADE:", peer)
        if self._opening_message:
            self._write(self._opening_message)

    def connection_lost(self, exc):
        """Called when the connection is lost or closed."""
        if self.debug:
            peer = self.transport.get_extra_info("peername")
            print("PJLinkServerProtocol CONNECTION_LOST:", peer)

    def data_received(self, data):
        """Called when the projector recieves data from the client."""
        if self.debug:
            print("PJLinkServerProtocol RECV:", data)

        # Buffer up writes until we get a terminator.
        self._recv_buffer += data
        if self._recv_buffer.endswith(b"\r"):
            # Handle bad test case programming.
            if not len(self._expected_events):
                raise NoExpectations("mock projector got a message before it was told to expect data")

            # Pop the next expected event off.
            expected = self._expected_events.pop(0)

            # If the client sent an _unexpected_ message, flag it as incorrect
            # then save the contents of the buffer, and close the connection.
            if self._recv_buffer != expected.incoming:
                if self.debug:
                    print("PJLinkServerProtocol UNEXPECTED:", self._recv_buffer, "expected", expected.incoming)
                expected.recv_buffer_contents = self._recv_buffer[:]
                self.loop.call_soon_threadsafe(expected.set)
                self._recv_buffer = b""
                self.transport.close()

            # If the client sent an _expected_ message, flag it as correct,
            # save the buffer contents, and then reply with the expected
            # response.
            else:
                expected.recv_buffer_contents = self._recv_buffer[:]
                self.loop.call_soon_threadsafe(expected.set)
                self.transport.write(expected.respond_with)
                self._recv_buffer = b""

    def open_and_send(self, message):
        """Set the message to send to the client when a connection is first established."""
        self._opening_message = message

    @contextlib.asynccontextmanager
    async def when(self, incoming, respond_with, within=1):
        """
        When the projector recieves an incoming message, it should respond with
        a reply within n seconds.

        If the projector recieves nothing from the client, raise `NoClientMessage`.
        If the projector recieves a different message, raise `UnexpectedClientMessage`.

        Other exceptions are passed through for handling by the test case.
        """
        # Define the expected incoming message and response.
        expected = ExpectedEvent(incoming, respond_with, within=within)
        self._expected_events.append(expected)

        # Give the event back to the application.
        try:
            yield expected
            await asyncio.wait_for(expected.wait(), timeout=expected.timeout)

        # Our mock protocol closes the server if it finds an error.
        # This results in the client seeing a disconnection (it doesn't know its mocked)
        # so we check the result of our event.

        # Handle reasons our tests might not be written correctly.
        except asyncio.exceptions.TimeoutError as err:
            # print("⌚ probably no message from client")
            if not expected.recv_buffer_contents:
                raise NoClientMessage(f"projector recieved no data from client (within={expected.timeout}s)") from err

        except aiopjlink.PJLinkConnectionClosed:
            # print("🚌 probably transport closed on purpose after bad message")
            # Check the object state to see if it got a bad message.
            if expected.recv_buffer_contents != expected.incoming:
                raise UnexpectedClientMessage(
                    f"projector expected {expected.incoming!r} from the client "
                    f"but got {expected.recv_buffer_contents!r}"
                ) from None

        # Ensure the event is removed.
        # Handles the edge case where the client API raises an exception before transmission.
        finally:
            # # Check the object state to see if it ever got a message from the client.
            # print("📋 expected.incoming", expected.incoming)
            # print("📋 expected.recv_buffer_contents", expected.recv_buffer_contents)

            if expected in self._expected_events:
                self._expected_events.remove(expected)


class ExpectedEvent(asyncio.Event):
    """
    Specalised event that controls what the mocked projector
    does next and validates that it behaves in the expected way.
    """

    def __init__(self, incoming, respond_with, within):
        super().__init__()
        # What the projector expects to recieve from the client.
        self.incoming = incoming

        # What should the projector respond with when it receives the expected
        # message from the client. NOTE: If it doesn't get the expected message
        # it hangs up the connection.  In this way, simulated projector errors
        # need to be implemented by the test cases.
        self.respond_with = respond_with

        # How long does the client have to do its thing.
        self.timeout = within

        # Contents of the projector recieve buffer after processing.
        self.recv_buffer_contents = None


@contextlib.asynccontextmanager
async def mock_tcp_pjlink(host="127.0.0.1", port=4352, password=None):
    loop = asyncio.get_running_loop()
    protocol = PJLinkServerProtocol(loop=loop)
    server = await loop.create_server(lambda: protocol, host, port)
    try:
        server_task = loop.create_task(server.serve_forever())
        yield protocol
    finally:
        server_task.cancel()


@contextlib.asynccontextmanager
async def mock_client_server_noauth():
    async with mock_tcp_pjlink() as server:
        server.open_and_send(b"PJLINK 0\r")
        client = aiopjlink.PJLink(address="127.0.0.1", password=None)
        yield server, client


@contextlib.asynccontextmanager
async def raw_tcp_server(handler, host="127.0.0.1", port=4352):
    """A bare-bones server for misbehaviour the mock projector can't simulate
    (e.g. hanging up in the middle of a command). `handler(reader, writer)` is
    called for every connection.
    """
    server = await asyncio.start_server(handler, host, port)
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()
