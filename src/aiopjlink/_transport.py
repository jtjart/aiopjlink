"""_transport.py

How a command gets to the projector and its answer back (§3.1, §5).

`Transport` knows about sockets, authentication and the wire format, but nothing
about individual commands. The groups in `aiopjlink.commands` depend on it, and
`PJLink` builds on it, so the dependency only ever points one way.

Connection handling
-------------------
The spec lets a controller send any number of commands on one TCP connection as
long as each follows the previous answer within 30 seconds (§5.3), and it says the
authentication data may be left out after the first command. The projector drops a
connection that stays silent for 30 seconds (§5.4, §6).

By default (`persistent=True`) a `Transport` therefore keeps the connection of the last
command and reuses it for the next one. That saves the connect, greeting and
authentication round trips for every command after the first. The connection is opened
lazily, replaced transparently when it is gone, and released after `idle_timeout`
seconds without traffic so that a projector which accepts a single controller is not
blocked longer than necessary.

`idle_timeout` also sets how long the connection lives for a projector that dislikes long
sessions: a short one (a second or two) makes it "one connection per burst of commands",
e.g. one per poll of a Home Assistant integration that sends three commands at once.
With `persistent=False` every command gets a connection of its own, which is what §5.4
literally asks for and the safe choice for projectors that cannot handle a second
command on one connection.

Either way a command has one deadline (`timeout`) that covers everything it does:
connecting, the greeting, sending and waiting for the answer.
"""

import asyncio
import dataclasses
from types import TracebackType
from typing import Self

from ._auth import build_request
from ._debug import LOGGER
from ._protocol import format_command, parse_response
from .enums import PJClass
from .exceptions import (
    PJLinkConnectionClosed,
    PJLinkNoConnection,
    PJLinkPassword,
    PJLinkProjectorError,
    PJLinkProtocolError,
)

_TIMEOUT_ERRORS: dict[str, str] = {
    "connect": "timeout - projector did not accept the connection in time",
    "greeting": "timeout - projector did not send a welcome message in time",
    "send": "timeout - projector did not accept the command in time",
    "response": "timeout - projector did not respond in time",
}

# The projector closes a connection after 30 s without a command (§5.4, §6). Let go of it a little earlier.
DEFAULT_IDLE_TIMEOUT = 25.0

# Politely closing a connection waits for the projector to acknowledge. Never wait longer than this for it.
_CLOSE_TIMEOUT = 1.0


@dataclasses.dataclass(slots=True)
class _Session:
    """One open TCP connection to the projector."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    greeting: str | None = None
    """The welcome line, kept until the first command has been built from it (§5.1, §5.3)."""

    @property
    def usable(self) -> bool:
        """False once the projector or the network has closed the connection."""
        return not (self.writer.is_closing() or self.reader.at_eof() or self.reader.exception() is not None)


class Transport:
    """Sends PJLink commands to a projector and returns the response parameter.

    One object can safely be shared between several tasks: commands are sent one
    after the other. There is nothing to open: the connection is made by the first
    command. Call `close` (or use the object as an `async with` block) when you are
    done, so that a connection kept for reuse is released.
    """

    def __init__(
        self,
        address: str,
        port: int = 4352,
        password: str | None = None,
        timeout: float = 4,
        encoding: str = "utf-8",
        *,
        persistent: bool = True,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        if idle_timeout <= 0:
            raise ValueError("idle_timeout must be positive (use persistent=False for one connection per command)")
        self._address = address
        self._port = port
        self._encoding = encoding
        self._timeout = timeout
        self._password = password
        self._persistent = persistent
        self._idle_timeout = idle_timeout

        # One command at a time: many projectors only accept a single connection, and the
        # answer to a command must not be mixed up with the answer to another one.
        self._lock = asyncio.Lock()

        # The connection kept for the next command. Only set while no command is running:
        # a command takes it for its duration and hands it back (or throws it away) at the end.
        self._session: _Session | None = None
        self._idle_timer: asyncio.TimerHandle | None = None

    @property
    def persistent(self) -> bool:
        """True if the connection is kept open and reused, False if every command opens its own."""
        return self._persistent

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the connection kept for reuse, if there is one.

        Safe to call at any time and more than once. A command that is still running
        finishes first (it is bounded by `timeout`). The object stays usable: the next
        command simply connects again. Does nothing if `persistent` is False.
        """
        async with self._lock:
            session = self._take_session()
            if session is not None:
                await self._close(session)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _read_next(self, reader: asyncio.StreamReader) -> str:
        """Read data until the next terminator (CR) and return the
        message (including CR) as a decoded string.
        """
        try:
            raw = await reader.readuntil(b"\r")
        except asyncio.IncompleteReadError as err:
            raise PJLinkConnectionClosed("projector closed the connection") from err
        except asyncio.LimitOverrunError as err:
            raise PJLinkProtocolError("response from projector is too long") from err
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err

        try:
            return raw.decode(self._encoding)
        except UnicodeDecodeError as err:
            raise PJLinkProtocolError("response from projector could not be decoded") from err

    async def transmit(self, command: str, param: str, pjclass: PJClass) -> str:
        """Send a command, authenticating and connecting first if needed, and return the response parameter.

        Calls on the same `PJLink` object are serialised, so this can be called
        from several tasks at once. The whole call, from connecting to the answer,
        is bound by `timeout`.

        Raises a subclass of `PJLinkException` for anything that goes wrong
        while talking to the projector (see the module documentation).
        """

        # Reject malformed commands before touching the network.
        cstring = format_command(command, param, pjclass)

        async with self._lock:
            # Queries have no side effects, so they may be repeated if a reused connection turns out to be dead.
            return await self._transmit(command, cstring, pjclass, retry=param.startswith("?"))

    async def _transmit(self, command: str, cstring: str, pjclass: PJClass, *, retry: bool) -> str:
        """Does the actual work of `transmit`. Must only be called with the lock held.

        `retry` allows one more attempt on a new connection if the kept connection was closed
        by the projector in the meantime. A command that changes something must not be repeated:
        the projector may have carried it out before it hung up.
        """

        session = self._take_session()
        phase = "connect"  # What was going on if the deadline expires.
        in_sync = False  # True once a complete answer was read: the connection can carry another command.
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    reused = session is not None
                    try:
                        if session is None:
                            # 1. Open connection
                            phase = "connect"
                            session = await self._open()

                            # 2. Read welcome/auth message
                            # Projector sends first message to identify itself as PJLINK.
                            phase = "greeting"
                            session.greeting = await self._read_next(session.reader)
                            LOGGER.debug("received welcome/authentication message")

                        # 3. Authenticate if needed and send command
                        phase = "send"
                        await self._send(session, cstring)

                        # 4. Read response
                        phase = "response"
                        response = await self._read_next(session.reader)
                        break
                    except PJLinkConnectionClosed:
                        # A connection that was open for a while may have been closed by the projector
                        # just now (§5.4), or the projector hangs up after every answer. Connect again, once.
                        if session is None or not (reused and retry):
                            raise
                        LOGGER.debug("reused connection was closed by the projector, reconnecting")
                        self._abort(session)
                        session = None

                # Read the first few bytes of the response - check for failed auth.
                if response.upper() == "PJLINK ERRA\r":
                    raise PJLinkPassword("authentication failed")

                # 5. Parse response
                try:
                    _, param = parse_response(response, expect_command=command, expect_pjclass=pjclass)
                except PJLinkProjectorError:
                    # The projector answered, with an error: the answer was read completely.
                    in_sync = True
                    raise
                in_sync = True
                return param

        except TimeoutError as err:
            raise PJLinkNoConnection(_TIMEOUT_ERRORS[phase]) from err

        finally:
            await self._release(session, keep=in_sync)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _open(self) -> _Session:
        """Open a connection. The caller is responsible for the deadline."""
        try:
            reader, writer = await asyncio.open_connection(self._address, self._port)
        except OSError as err:
            raise PJLinkNoConnection("connection failed") from err
        LOGGER.debug("connected to %s:%s", self._address, self._port)
        return _Session(reader, writer)

    async def _send(self, session: _Session, cstring: str) -> None:
        """Send a command line, with the authentication data in front if this is the first one (§5.1, §5.3)."""
        if session.greeting is not None:
            cbytes = build_request(session.greeting, cstring, self._password, self._encoding)
            session.greeting = None
        else:
            # Authenticated already: the spec allows the digest to be left out from now on.
            cbytes = cstring.encode(self._encoding)

        LOGGER.debug("sending command: %s", cstring.strip())
        try:
            session.writer.write(cbytes)
            await session.writer.drain()
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err

    def _take_session(self) -> _Session | None:
        """Take the kept connection for the duration of a command. None if there is no usable one."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        session, self._session = self._session, None
        if session is not None and not session.usable:
            LOGGER.debug("kept connection is gone")
            self._abort(session)
            return None
        return session

    async def _release(self, session: _Session | None, *, keep: bool) -> None:
        """Finish with a connection after a command.

        `keep` says the connection is in a known state (the last answer was read completely).
        Otherwise it is thrown away: a late answer to this command must never be taken for
        the answer to the next one.
        """
        if session is None:
            return
        if not keep:
            self._abort(session)
        elif self._persistent:
            self._session = session
            self._idle_timer = asyncio.get_running_loop().call_later(self._idle_timeout, self._close_idle)
        else:
            await self._close(session)

    def _close_idle(self) -> None:
        """Timer callback: nothing was sent for `idle_timeout` seconds, so let go of the projector."""
        self._idle_timer = None
        session, self._session = self._session, None
        if session is not None:
            LOGGER.debug("closing idle connection")
            session.writer.close()

    @staticmethod
    async def _close(session: _Session) -> None:
        """Close a connection in good order, but wait at most `_CLOSE_TIMEOUT` for the projector to acknowledge."""
        session.writer.close()
        try:
            await asyncio.wait_for(session.writer.wait_closed(), _CLOSE_TIMEOUT)
        except OSError:  # Includes TimeoutError.
            session.writer.transport.abort()

    @staticmethod
    def _abort(session: _Session) -> None:
        """Drop a connection at once, without waiting for anything. Nothing can hang here."""
        session.writer.transport.abort()
