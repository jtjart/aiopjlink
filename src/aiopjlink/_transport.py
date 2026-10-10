"""_transport.py

How a command gets to the projector and its answer back (§3.1, §5).

`Transport` knows about sockets, authentication and the wire format, but nothing
about individual commands. The groups in `aiopjlink.commands` depend on it, and
`PJLink` builds on it, so the dependency only ever points one way.
"""

import asyncio
import contextlib

from ._auth import build_request
from ._debug import LOGGER
from ._protocol import format_command, parse_response
from .enums import PJClass
from .exceptions import (
    PJLinkConnectionClosed,
    PJLinkNoConnection,
    PJLinkPassword,
    PJLinkProtocolError,
)

_TIMEOUT_ERRORS: dict[str, str] = {
    "connect": "timeout - projector did not accept the connection in time",
    "greeting": "timeout - projector did not send a welcome message in time",
    "send": "timeout - projector did not accept the command in time",
    "response": "timeout - projector did not respond in time",
}


class Transport:
    """Sends PJLink commands to a projector and returns the response parameter.

    Every command opens its own short-lived connection, so there is nothing to
    open or close. One object can safely be shared between several tasks:
    commands are sent one after the other.
    """

    def __init__(
        self,
        address: str,
        port: int = 4352,
        password: str | None = None,
        timeout: float = 4,
        encoding: str = "utf-8",
    ) -> None:
        self._address = address
        self._port = port
        self._encoding = encoding
        self._timeout = timeout
        self._password = password

        # One command at a time: many projectors only accept a single connection.
        self._lock = asyncio.Lock()

    async def _read_next(self, reader: asyncio.StreamReader) -> str:
        """Read data until the next terminator (CR) and return the
        message (including CR) as a decoded string.

        Raises `asyncio.TimeoutError` if nothing arrives in time, so that the caller
        can decide what a timeout means at that point of the conversation.
        """
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r"), self._timeout)
        except asyncio.IncompleteReadError as err:
            raise PJLinkConnectionClosed("projector closed the connection") from err
        except asyncio.LimitOverrunError as err:
            raise PJLinkProtocolError("response from projector is too long") from err
        except TimeoutError:
            raise
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err

        try:
            return raw.decode(self._encoding)
        except UnicodeDecodeError as err:
            raise PJLinkProtocolError("response from projector could not be decoded") from err

    async def transmit(self, command: str, param: str, pjclass: PJClass) -> str:
        """Open connection, authenticate, send command, get response, close connection.

        Calls on the same `PJLink` object are serialised, so this can be called
        from several tasks at once.

        Raises a subclass of `PJLinkException` for anything that goes wrong
        while talking to the projector (see the module documentation).
        """

        # Reject malformed commands before touching the network.
        cstring = format_command(command, param, pjclass)

        async with self._lock:
            return await self._transmit(command, cstring, pjclass)

    async def _transmit(self, command: str, cstring: str, pjclass: PJClass) -> str:
        """Does the actual work of `transmit`. Must only be called with the lock held."""

        # The connection lives in local variables, not on the object, so nothing is shared between calls.
        writer = None
        try:
            async with asyncio.timeout(self._timeout):
                # 1. Open connection
                phase = "connect"
                try:
                    reader, writer = await asyncio.open_connection(self._address, self._port)
                except OSError as err:
                    raise PJLinkNoConnection("connection failed") from err

                # An authentication procedure should be executed once after each establishment of TCP/IP connection.
                # But for some reason this does not work with AWOL projector - 1 command = 1 connection
                # The authentication procedure involves a password verification process.
                # See https://pjlink.jbmia.or.jp/english/data_cl2/PJLink_5-1.pdf SECTION 5

                # 2. Read welcome/auth message
                # Projector sends first message to identify itself as PJLINK.
                phase = "greeting"
                data = await self._read_next(reader)
                LOGGER.debug("received welcome/authentication message")

                # 3. Authenticate if needed and send command
                phase = "send"
                cbytes = build_request(data, cstring, self._password, self._encoding)
                LOGGER.debug("sending command: %s", cstring.strip())
                try:
                    writer.write(cbytes)
                    await writer.drain()
                except OSError as err:
                    raise PJLinkConnectionClosed(f"connection error - {err}") from err

                # 4. Read response
                # Read the first few bytes of the response - check for failed auth.
                phase = "response"
                response = await self._read_next(reader)
                if response.upper() == "PJLINK ERRA\r":
                    raise PJLinkPassword("authentication failed")

                # 5. Parse response
                _, param = parse_response(response, expect_command=command, expect_pjclass=pjclass)
                return param

        except TimeoutError as err:
            raise PJLinkNoConnection(_TIMEOUT_ERRORS[phase]) from err

        finally:
            if writer is not None:
                writer.close()
                with contextlib.suppress(asyncio.TimeoutError, ConnectionError, OSError):
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
