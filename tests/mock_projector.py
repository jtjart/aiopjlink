"""A mock PJLink projector for the tests.

Provides a full socket stack so the client can be tested against a projector,
including erroneous behaviour. See `PJLinkServerProtocol.when`.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast

import aiopjlink2

LOCALHOST = "127.0.0.1"


def client_for(port: int, **options: Any) -> aiopjlink2.PJLink:
    """A `PJLink` for the mock projector on `port` (no password unless `options` give one)."""
    options.setdefault("password", None)
    return aiopjlink2.PJLink(address=LOCALHOST, port=port, **options)


def unused_port() -> int:
    """A port nothing listens on: asked from the OS and given back at once."""
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        return cast(int, sock.getsockname()[1])


def unused_udp_port() -> int:
    """A local UDP port nothing is using: asked from the OS and given back at once."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((LOCALHOST, 0))
        return cast(int, sock.getsockname()[1])


def ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.bind(("::1", 0))
    except OSError:
        return False
    return True


async def search_all(**arguments: Any) -> list[aiopjlink2.SearchResult]:
    """Run `aiopjlink2.search` to the end and return everything it found."""
    return [result async for result in aiopjlink2.search(**arguments)]


class PJLinkTestFrameworkError(Exception):
    """Base exception for problems with the test framework."""


class NoClientMessageError(PJLinkTestFrameworkError):
    """The test case fails because the test case didn't send a client message."""


class UnexpectedClientMessageError(PJLinkTestFrameworkError):
    """The test case fails because the test case expected something the client didn't send."""


class NoExpectationsError(PJLinkTestFrameworkError):
    """The test case fails because the mock projector receives a command before it is told how to respond."""


class PJLinkServerProtocol(asyncio.Protocol):
    """
    Provides a method for mocking a projector, including a full socket
    stack to provide a proper simulation of a projector for the client - including
    erroneous behaviours.

    This class has some nuance - check it here.
    https://docs.python.org/3/library/asyncio-protocol.html
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, debug: bool = False) -> None:
        self.loop = loop
        self.debug = debug

        # Sent as soon as a connection is established.
        self._opening_message: bytes | None = None

        # What the projector should expect to receive next and how to react (as defined by the test case).
        self._expected_events: list[ExpectedEvent] = []

        # What has arrived so far of the message in progress. A message ends with CR.
        self._receive_buffer = b""

        # The port the server listens on (chosen by the OS, set by `mock_tcp_pjlink`).
        self.port = 0

        # The server side of the current connection (set by `connection_made`).
        self.transport: asyncio.Transport

    def client(self, **options: Any) -> aiopjlink2.PJLink:
        """A `PJLink` connected to this mock projector. `options` are passed on to `PJLink`."""
        return client_for(self.port, **options)

    def _write(self, data: bytes) -> None:
        if self.debug:
            print("PJLinkServerProtocol SEND:", data)
        self.transport.write(data)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.Transport, transport)
        if self.debug:
            peer = self.transport.get_extra_info("peername")
            print("PJLinkServerProtocol CONNECTION_MADE:", peer)
        if self._opening_message:
            self._write(self._opening_message)

    def connection_lost(self, exc: Exception | None) -> None:
        if self.debug:
            peer = self.transport.get_extra_info("peername")
            print("PJLinkServerProtocol CONNECTION_LOST:", peer)

    def data_received(self, data: bytes) -> None:
        if self.debug:
            print("PJLinkServerProtocol RECV:", data)

        self._receive_buffer += data
        if self._receive_buffer.endswith(b"\r"):
            if not len(self._expected_events):
                raise NoExpectationsError("mock projector got a message before it was told to expect data")

            expected = self._expected_events.pop(0)

            # A message other than the expected one is recorded for `when` to report, and the connection is
            # closed, which the client sees as a disconnection.
            if self._receive_buffer != expected.incoming:
                if self.debug:
                    print("PJLinkServerProtocol UNEXPECTED:", self._receive_buffer, "expected", expected.incoming)
                expected.receive_buffer_contents = self._receive_buffer[:]
                self.loop.call_soon_threadsafe(expected.received.set)
                self._receive_buffer = b""
                self.transport.close()
            else:
                expected.receive_buffer_contents = self._receive_buffer[:]
                self.loop.call_soon_threadsafe(expected.received.set)
                self.transport.write(expected.respond_with)
                self._receive_buffer = b""

    def open_and_send(self, message: bytes) -> None:
        """Set the message to send to the client when a connection is first established."""
        self._opening_message = message

    @contextlib.asynccontextmanager
    async def when(
        self, incoming: bytes, respond_with: bytes, within_seconds: float = 1
    ) -> AsyncGenerator["ExpectedEvent", None]:
        """
        When the projector receives an incoming message, it should respond with
        a reply within n seconds.

        If the projector receives nothing from the client, raise `NoClientMessageError`.
        If the projector receives a different message, raise `UnexpectedClientMessageError`.

        Other exceptions are passed through for handling by the test case.
        """
        expected = ExpectedEvent(incoming, respond_with, within_seconds=within_seconds)
        self._expected_events.append(expected)

        try:
            yield expected
            await asyncio.wait_for(expected.received.wait(), timeout=expected.timeout_seconds)

            # The projector hangs up on a message it did not expect. A client that reconnects after a
            # hang-up (see `aiopjlink2.client`) does not see an error, so check the message here as well.
            if expected.receive_buffer_contents != expected.incoming:
                raise UnexpectedClientMessageError(
                    f"projector expected {expected.incoming!r} from the client "
                    f"but got {expected.receive_buffer_contents!r}"
                )

        except asyncio.exceptions.TimeoutError as err:
            # No complete message arrived from the client in time.
            if not expected.receive_buffer_contents:
                raise NoClientMessageError(
                    f"projector recieved no data from client (within={expected.timeout_seconds}s)"
                ) from err

        except aiopjlink2.PJLinkConnectionClosedError:
            # The mock hangs up on a message it did not expect (see `data_received`).
            if expected.receive_buffer_contents != expected.incoming:
                raise UnexpectedClientMessageError(
                    f"projector expected {expected.incoming!r} from the client "
                    f"but got {expected.receive_buffer_contents!r}"
                ) from None

        except aiopjlink2.PJLinkAuthenticationError:
            # A wrong password makes a projector hang up (or send ERRA). If the message was not the one
            # the test expected, that is a test bug; otherwise let the test case see the error.
            if expected.receive_buffer_contents != expected.incoming:
                raise UnexpectedClientMessageError(
                    f"projector expected {expected.incoming!r} from the client "
                    f"but got {expected.receive_buffer_contents!r}"
                ) from None
            raise

        finally:
            # The client API can raise before it transmits anything, which leaves the event waiting: remove it.
            if expected in self._expected_events:
                self._expected_events.remove(expected)


class ExpectedEvent:
    """What the mocked projector expects to receive next, and how it reacts."""

    def __init__(self, incoming: bytes, respond_with: bytes, within_seconds: float) -> None:
        self.incoming = incoming
        self.respond_with = respond_with
        self.timeout_seconds = within_seconds
        self.receive_buffer_contents: bytes | None = None
        self.received = asyncio.Event()


@contextlib.asynccontextmanager
async def mock_tcp_pjlink(
    host: str = LOCALHOST, port: int = 0, password: str | None = None
) -> AsyncGenerator[PJLinkServerProtocol, None]:
    """A mock projector on a free port (`port=0`: the OS picks one, so tests do not collide with anything)."""
    loop = asyncio.get_running_loop()
    protocol = PJLinkServerProtocol(loop=loop)
    server = await loop.create_server(lambda: protocol, host, port)
    protocol.port = server.sockets[0].getsockname()[1]
    server_task = loop.create_task(server.serve_forever())
    try:
        yield protocol
    finally:
        server_task.cancel()


@contextlib.asynccontextmanager
async def mock_client_server_noauth(
    **client_options: Any,
) -> AsyncGenerator[tuple[PJLinkServerProtocol, aiopjlink2.PJLink], None]:
    """A mock projector without authentication and a client connected to it.

    `client_options` are passed on to `PJLink` (e.g. `persistent=False`). The client is closed afterwards.
    """
    async with mock_tcp_pjlink() as server:
        server.open_and_send(b"PJLINK 0\r")
        client = server.client(**client_options)
        try:
            yield server, client
        finally:
            await client.close()


class RawServer:
    """What `raw_tcp_server` yields: the port it listens on and a client for it."""

    def __init__(self, server: asyncio.Server) -> None:
        self.port: int = server.sockets[0].getsockname()[1]

    def client(self, **options: Any) -> aiopjlink2.PJLink:
        """A `PJLink` connected to this server. `options` are passed on to `PJLink`."""
        return client_for(self.port, **options)


@contextlib.asynccontextmanager
async def raw_tcp_server(
    handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    host: str = LOCALHOST,
    port: int = 0,
) -> AsyncGenerator[RawServer, None]:
    """A bare-bones server for misbehaviour the mock projector can't simulate
    (e.g. hanging up in the middle of a command). `handler(reader, writer)` is
    called for every connection. Like `mock_tcp_pjlink` it listens on a free port.
    """
    server = await asyncio.start_server(handler, host, port)
    try:
        yield RawServer(server)
    finally:
        server.close()
        await server.wait_closed()


async def until_hung_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Wait for the client to disconnect, then close our side."""
    await reader.read()
    writer.close()
