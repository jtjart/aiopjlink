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
lazily, replaced transparently when it is gone, and released after `idle_timeout_seconds`
without traffic so that a projector which accepts a single controller is not
blocked longer than necessary.

`idle_timeout_seconds` also sets how long the connection lives for a projector that dislikes long
sessions: a short one (a second or two) makes it "one connection per burst of commands",
e.g. one per poll of a Home Assistant integration that sends three commands at once.
With `persistent=False` every command gets a connection of its own, which is what §5.4
literally asks for and the safe choice for projectors that cannot handle a second
command on one connection.

Either way a command has one deadline (`timeout_seconds`) that covers everything it does:
connecting, the greeting, sending and waiting for the answer.

A kept connection can hold data nobody asked for: some projectors volunteer a status line (e.g. `%1powr=0` a moment
after a power-on command) or repeat an answer. Nothing can be the answer to a command that has not been sent yet, so
whatever has arrived by then is thrown away before the next command goes out. Otherwise it would be taken for that
command's answer: an "unexpected response command" error, or a wrong value if the command happens to be the same.

Authentication
--------------
A projector with security on greets with `PJLINK 1 <token>`. Specification 2.10 (§5.1) then lets the
controller ask for SHA256 by sending `PJLINK 2`; a projector that supports it answers with a random number
and the first command carries a SHA256 digest instead of the MD5 one. Anything else the projector does in reply
(`ERR1`, `ERR2`, `ERRA`, an echo, hanging up, silence) means "MD5 only": the connection is dropped and a new one
is made with the original MD5 procedure (see `PJAuth`).

The question costs one round trip per connection, and a projector that stays silent costs
`_SHA256_INQUIRY_TIMEOUT_SECONDS` once: from the moment a projector has not answered the question with a yes, MD5
is assumed and later connections do not ask again. (A projector that cannot cope with the question would otherwise
be disturbed by every new connection; one that merely missed it is put right by what follows.)

If MD5 is rejected (`ERRA`) by a projector that never said it does not do SHA256 (the question was skipped because
MD5 was assumed or worked before), it may be a SHA256 projector after all. The command then asks once more on a
new connection, for SHA256 only, with a deadline of its own. Nothing was carried out by the rejected command, so
repeating it is safe whatever it does.

Deadline
--------
`timeout_seconds` is how long a projector may take to answer. The exception is a command that carries a password digest:
a projector that dislikes it waits two seconds before saying so (§5.1), and that must come out as
`PJLinkPassword`, not as a dead connection, so such a command is given at least `_MINIMUM_DIGEST_ANSWER_SECONDS`
to be answered, whatever `timeout_seconds` is.
"""

import asyncio
import dataclasses
from types import TracebackType
from typing import Self

from ._auth import SHA256_INQUIRY, build_md5_request, build_sha256_request, parse_security_reply, parse_welcome
from ._debug import LOGGER, redact_debug_payload
from ._protocol import format_command, parse_response
from .enums import PJAuth, PJClass
from .exceptions import (
    PJLinkConnectionClosed,
    PJLinkNoConnection,
    PJLinkNotSupported,
    PJLinkPassword,
    PJLinkProjectorError,
    PJLinkProtocolError,
)

_TIMEOUT_MESSAGES_BY_PHASE: dict[str, str] = {
    "connect": "timeout - projector did not accept the connection in time",
    "greeting": "timeout - projector did not send a welcome message in time",
    "security": "timeout - projector did not complete the security handshake in time",
    "send": "timeout - projector did not accept the command in time",
    "response": "timeout - projector did not respond in time",
}

# The projector closes a connection after 30 s without a command (§5.4, §6). Let go of it a little earlier.
DEFAULT_IDLE_TIMEOUT_SECONDS = 25.0

# Politely closing a connection waits for the projector to acknowledge. Never wait longer than this for it.
_CLOSE_TIMEOUT_SECONDS = 1.0

# Unsolicited data is discarded in chunks of this size (the most a `StreamReader` buffers by default).
_DISCARD_CHUNK_SIZE_BYTES = 2**16

# How long a projector gets to answer the SHA256 question (§5.1). One that is not going to answer must not use up
# the whole deadline of the command, which still needs time to reconnect: the wait is also capped at half of what
# is left of it.
_SHA256_INQUIRY_TIMEOUT_SECONDS = 2.0

# How long the answer to a command that carries a password digest may take: the two seconds a projector may wait
# before rejecting a digest (§5.1), and a second more. If `timeout_seconds` ends sooner, the deadline is moved to this.
_MINIMUM_DIGEST_ANSWER_SECONDS = 3.0


class _Md5Rejected(PJLinkPassword):
    """MD5 was rejected by a projector that may still do SHA256. Never leaves `Transport.transmit`."""


class _Sha256Refused(PJLinkNotSupported):
    """The projector does not do SHA256, found out on the second try. Never leaves `Transport.transmit`."""


@dataclasses.dataclass(slots=True)
class _Session:
    """One open TCP connection to the projector."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    greeting: str | None = None
    """The welcome line, kept until the first command has been built from it (§5.1, §5.3)."""

    sha256_nonce: str | None = None
    """The projector's random number, if it agreed to SHA256; kept until the first command has been built (§5.1)."""

    digest_sent: bool = False
    """True if the last command went out with authentication data in front of it."""

    authentication_method: PJAuth | None = None
    """Which procedure that authentication data belongs to: `PJAuth.SHA256` or `PJAuth.MD5`."""

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
        timeout_seconds: float = 4,
        encoding: str = "utf-8",
        *,
        persistent: bool = True,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        authentication: PJAuth | str = PJAuth.AUTO,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError(
                "idle_timeout_seconds must be positive (use persistent=False for one connection per command)"
            )
        self._authentication = PJAuth(authentication)
        self._address = address
        self._port = port
        self._encoding = encoding
        self._timeout_seconds = timeout_seconds
        self._password = password
        self._persistent = persistent
        self._idle_timeout_seconds = idle_timeout_seconds

        # One command at a time: many projectors only accept a single connection, and the
        # answer to a command must not be mixed up with the answer to another one.
        self._command_lock = asyncio.Lock()

        # The connection kept for the next command. Only set while no command is running:
        # a command takes it for its duration and hands it back (or throws it away) at the end.
        self._kept_session: _Session | None = None
        self._idle_close_timer: asyncio.TimerHandle | None = None

        # True once the projector has answered a command we sent a password digest with.
        self._password_accepted = False

        # The procedure the projector last accepted a password with (`PJAuth.SHA256` or `PJAuth.MD5`), if any.
        # Only a success is remembered: a silent projector may just be having a bad moment.
        self._learned_authentication_method: PJAuth | None = None

    @property
    def persistent(self) -> bool:
        """True if the connection is kept open and reused, False if every command opens its own."""
        return self._persistent

    @property
    def authentication(self) -> PJAuth:
        """The authentication this object was asked to use (`PJAuth.AUTO` unless set otherwise)."""
        return self._authentication

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the connection kept for reuse, if there is one.

        Safe to call at any time and more than once. A command that is still running
        finishes first (it is bounded by `timeout_seconds`). The object stays usable: the next
        command simply connects again. Does nothing if `persistent` is False.
        """
        async with self._command_lock:
            session = self._take_session()
            if session is not None:
                await self._close_session(session)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _read_line(self, reader: asyncio.StreamReader) -> str:
        """Read data until the next terminator (CR) and return the
        message (including CR) as a decoded string.
        """
        try:
            raw_line = await reader.readuntil(b"\r")
        except asyncio.IncompleteReadError as err:
            raise PJLinkConnectionClosed("projector closed the connection") from err
        except asyncio.LimitOverrunError as err:
            raise PJLinkProtocolError("response from projector is too long") from err
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err

        # The spec prescribes UTF-8, but free text (a projector name, say) does turn up in other encodings. That must
        # not make the whole answer unreadable: undecodable bytes become U+FFFD. The fields that are not free text are
        # validated by their parsers anyway, so garbage still ends up as an error there.
        return raw_line.decode(self._encoding, errors="replace").lstrip("\n")

    async def transmit(self, command: str, parameter: str, pjclass: PJClass) -> str:
        """Send a command, authenticating and connecting first if needed, and return the response parameter.

        Calls on the same `PJLink` object are serialised, so this can be called
        from several tasks at once. The whole call, from connecting to the answer,
        is bound by `timeout_seconds`.

        Raises a subclass of `PJLinkException` for anything that goes wrong
        while talking to the projector (see the module documentation).
        """

        # Reject malformed commands before touching the network.
        command_line = format_command(command, parameter, pjclass, self._encoding)

        async with self._command_lock:
            # Queries have no side effects, so they may be repeated if a reused connection turns out to be dead.
            is_query = parameter.startswith("?")
            try:
                return await self._attempt_transmit(
                    command,
                    command_line,
                    pjclass,
                    may_retry_on_new_connection=is_query,
                    budget_seconds=self._timeout_seconds,
                )
            except _Md5Rejected:
                # The projector rejected the digest, so it did not carry out the command: asking again is safe even
                # for a command that changes something. The second try is for SHA256 only, so a wrong password is
                # not rejected twice, and it has a deadline of its own: the first try ended with an answer, so the
                # projector is there.
                LOGGER.debug("MD5 was rejected by a projector that may do SHA256, asking again")
                try:
                    return await self._attempt_transmit(
                        command,
                        command_line,
                        pjclass,
                        may_retry_on_new_connection=is_query,
                        budget_seconds=self._timeout_seconds,
                        sha256_only=True,
                    )
                except _Sha256Refused:
                    raise PJLinkPassword("authentication failed") from None

    async def _attempt_transmit(
        self,
        command: str,
        command_line: str,
        pjclass: PJClass,
        *,
        may_retry_on_new_connection: bool,
        budget_seconds: float,
        sha256_only: bool = False,
    ) -> str:
        """Does the actual work of `transmit`. Must only be called with the lock held.

        `may_retry_on_new_connection` allows one more attempt on a new connection if the kept connection was closed
        by the projector in the meantime. A command that changes something must not be repeated:
        the projector may have carried it out before it hung up.

        `budget_seconds` is how long this attempt may take (but see `_MINIMUM_DIGEST_ANSWER_SECONDS`).
        `sha256_only` is the second try after a rejected MD5 digest: it asks for SHA256 and never falls back
        (`_Sha256Refused` if the projector does not do it).
        """

        session = self._take_session()
        phase = "connect"  # What was going on if the deadline expires.
        connection_reusable = False  # True once a complete answer was read: the connection can carry another command.
        projector_declined_sha256 = (
            False  # True once the projector has answered the SHA256 question with something but yes.
        )
        try:
            async with asyncio.timeout(budget_seconds) as deadline:
                ask_for_sha256 = sha256_only or self._should_ask_for_sha256()
                while True:
                    session_was_reused = session is not None
                    try:
                        if session is None:
                            # 1. Open connection
                            phase = "connect"
                            session = await self._open_session()

                            # 2. Read welcome/auth message
                            # Projector sends first message to identify itself as PJLINK.
                            phase = "greeting"
                            session.greeting = await self._read_line(session.reader)
                            LOGGER.debug("received welcome/authentication message")

                            # 3. Ask a projector that wants a password whether it does SHA256 (§5.1).
                            # Anything but a yes means: drop this connection and start again with MD5.
                            if ask_for_sha256:
                                phase = "security"
                                sha256_supported = await self._negotiate_sha256(session, deadline)
                                if sha256_supported is not True:
                                    self._abort_session(session)
                                    session = None
                                    if self._authentication is PJAuth.SHA256:
                                        raise PJLinkNotSupported("SHA256 authentication not supported by the projector")
                                    if sha256_only:
                                        raise _Sha256Refused("SHA256 authentication not supported by the projector")
                                    projector_declined_sha256 = sha256_supported is False
                                    # Assumed from now on, even if the new connection fails: a projector that cannot
                                    # cope with the question must not be asked again by every connection. If it was a
                                    # SHA256 projector that missed it, the rejected MD5 digest puts that right.
                                    self._learned_authentication_method = PJAuth.MD5
                                    LOGGER.debug("projector does not support SHA256, reconnecting to use MD5")
                                    ask_for_sha256 = False
                                    continue
                        else:
                            # The connection was kept: whatever is waiting on it is not the answer to this command.
                            await self._discard_unsolicited(session)

                        # 4. Authenticate if needed and send command
                        phase = "send"
                        await self._send(session, command_line)
                        if session.digest_sent:
                            # A projector that dislikes the digest answers only after two seconds (§5.1): that wait
                            # must not use up the deadline, or a wrong password would look like a dead connection.
                            deadline_time = deadline.when()
                            if deadline_time is not None:
                                deadline.reschedule(
                                    max(
                                        deadline_time,
                                        asyncio.get_running_loop().time() + _MINIMUM_DIGEST_ANSWER_SECONDS,
                                    )
                                )

                        # 5. Read response
                        phase = "response"
                        response_line = await self._read_line(session.reader)
                        break
                    except PJLinkConnectionClosed as err:
                        # Hung up right after the password went out, and it never worked before: a projector
                        # that rejects a password by closing instead of sending `ERRA`.
                        if (
                            phase == "response"
                            and session is not None
                            and session.digest_sent
                            and not self._password_accepted
                        ):
                            raise PJLinkPassword(
                                "projector closed the connection after the password was sent - "
                                "the password is probably wrong"
                            ) from err
                        # A connection that was open for a while may have been closed
                        if session is None or not (session_was_reused and may_retry_on_new_connection):
                            raise
                        LOGGER.debug("reused connection was closed by the projector, reconnecting")
                        self._abort_session(session)
                        session = None

                # Read the first few bytes of the response - check for failed auth.
                if response_line.upper() == "PJLINK ERRA\r":
                    if session.authentication_method is PJAuth.MD5:
                        if self._learned_authentication_method is PJAuth.MD5:
                            # MD5 worked before and does not any more (the projector may have been switched to
                            # SHA256, or the password changed): do not take it for granted any longer.
                            self._learned_authentication_method = None
                        if self._authentication is PJAuth.AUTO and not projector_declined_sha256:
                            # The projector never said it does not do SHA256: ask again (see `transmit`).
                            raise _Md5Rejected("authentication failed")
                    raise PJLinkPassword("authentication failed")
                if session.digest_sent:
                    self._password_accepted = True  # Any other complete answer means the password was accepted.
                    self._learned_authentication_method = session.authentication_method

                # 6. Parse response
                try:
                    _, response_parameter = parse_response(
                        response_line, expect_command=command, expect_pjclass=pjclass
                    )
                except PJLinkProjectorError:
                    # The projector answered, with an error: the answer was read completely.
                    connection_reusable = True
                    raise
                connection_reusable = True
                return response_parameter

        except TimeoutError as err:
            if sha256_only and phase == "response" and session is not None and session.digest_sent:
                # MD5 was rejected before, and now the projector sits on our SHA256 digest: a projector that dislikes
                # a digest answers only after two seconds (§5.1). The password is wrong, not the connection.
                raise PJLinkPassword("authentication failed") from err
            raise PJLinkNoConnection(_TIMEOUT_MESSAGES_BY_PHASE[phase]) from err

        finally:
            await self._release_session(session, connection_reusable=connection_reusable)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _open_session(self) -> _Session:
        """Open a connection. The caller is responsible for the deadline."""
        try:
            reader, writer = await asyncio.open_connection(self._address, self._port)
        except OSError as err:
            raise PJLinkNoConnection(f"connection failed - {err}") from err
        LOGGER.debug("connected to %s:%s", self._address, self._port)
        return _Session(reader, writer)

    def _should_ask_for_sha256(self) -> bool:
        """True if a new connection should ask the projector for SHA256 (§5.1)."""
        if self._authentication is PJAuth.MD5:
            return False
        return not (self._authentication is PJAuth.AUTO and self._learned_authentication_method is PJAuth.MD5)

    async def _negotiate_sha256(self, session: _Session, deadline: asyncio.Timeout) -> bool | None:
        """Ask a projector that wants a password whether it supports SHA256 (§5.1).

        Returns True if it does. Anything short of `PJLINK 2 <random number>` counts as "not" for the spec, which
        has the controller use MD5 then: `ERR1`, `ERR2`, `ERRA` (which is *not* a password error here), an echo
        (False: the projector said something), hanging up or silence for `_SHA256_INQUIRY_TIMEOUT_SECONDS`
        (None: it said nothing, which proves little, since a projector may just be having a bad moment).
        Raises `PJLinkProtocolError` for a welcome line that is not valid, before anything is sent.
        """
        if session.greeting is None or not parse_welcome(session.greeting).secured or self._password is None:
            # Nothing to ask: no password is needed, or none was given (`_send` reports that).
            return True

        deadline_time = deadline.when()
        remaining_seconds = (
            self._timeout_seconds
            if deadline_time is None
            else max(deadline_time - asyncio.get_running_loop().time(), 0.0)
        )
        try:
            async with asyncio.timeout(min(_SHA256_INQUIRY_TIMEOUT_SECONDS, remaining_seconds / 2)):
                LOGGER.debug("asking the projector for SHA256 security")
                session.writer.write(SHA256_INQUIRY.encode("ascii"))
                await session.writer.drain()
                security_reply = await self._read_line(session.reader)
        except (TimeoutError, PJLinkConnectionClosed, PJLinkProtocolError, OSError):
            LOGGER.debug("no answer to the security level inquiry")
            return None

        projector_nonce = parse_security_reply(security_reply)
        if projector_nonce is None:
            LOGGER.debug("security level inquiry answered with: %s", redact_debug_payload(security_reply.strip()))
            return False
        session.sha256_nonce = projector_nonce
        return True

    async def _send(self, session: _Session, command_line: str) -> None:
        """Send a command line, with the authentication data in front if this is the first one (§5.1, §5.3)."""
        command_without_digest = command_line.encode(self._encoding)
        session.authentication_method = None
        if session.sha256_nonce is not None and self._password is not None:
            request_bytes = build_sha256_request(session.sha256_nonce, command_line, self._password, self._encoding)
            session.sha256_nonce = None
            session.greeting = None
            session.authentication_method = PJAuth.SHA256
        elif session.greeting is not None:
            request_bytes = build_md5_request(session.greeting, command_line, self._password, self._encoding)
            session.greeting = None
            session.authentication_method = PJAuth.MD5
        else:
            # Authenticated already: the spec allows the digest to be left out from now on.
            request_bytes = command_without_digest
        session.digest_sent = request_bytes != command_without_digest
        if not session.digest_sent:
            session.authentication_method = None  # `PJLINK 0`: nothing was added to the command.

        LOGGER.debug("sending command: %s", command_line.strip())
        try:
            session.writer.write(request_bytes)
            await session.writer.drain()
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err

    @staticmethod
    async def _discard_unsolicited(session: _Session) -> None:
        """Throw away what the projector sent while no command was waiting for an answer. Never waits for more."""
        try:
            async with asyncio.timeout(0):  # Reads what has arrived already; if there is none, gives up at once.
                unsolicited_bytes = await session.reader.read(_DISCARD_CHUNK_SIZE_BYTES)
        except TimeoutError:  # Before OSError, which it is a subclass of.
            return
        except OSError as err:
            raise PJLinkConnectionClosed(f"connection error - {err}") from err
        if unsolicited_bytes:
            LOGGER.debug("discarded unsolicited data from the projector: %r", unsolicited_bytes)

    def _take_session(self) -> _Session | None:
        """Take the kept connection for the duration of a command. None if there is no usable one."""
        if self._idle_close_timer is not None:
            self._idle_close_timer.cancel()
            self._idle_close_timer = None
        session, self._kept_session = self._kept_session, None
        if session is not None and not session.usable:
            LOGGER.debug("kept connection is gone")
            self._abort_session(session)
            return None
        return session

    async def _release_session(self, session: _Session | None, *, connection_reusable: bool) -> None:
        """Finish with a connection after a command.

        `connection_reusable` says the connection is in a known state (the last answer was read completely).
        Otherwise it is thrown away: a late answer to this command must never be taken for
        the answer to the next one.
        """
        if session is None:
            return
        if not connection_reusable:
            self._abort_session(session)
        elif self._persistent:
            self._kept_session = session
            self._idle_close_timer = asyncio.get_running_loop().call_later(
                self._idle_timeout_seconds, self._close_idle_session
            )
        else:
            await self._close_session(session)

    def _close_idle_session(self) -> None:
        """Timer callback: nothing was sent for `idle_timeout_seconds`, so let go of the projector."""
        self._idle_close_timer = None
        session, self._kept_session = self._kept_session, None
        if session is not None:
            LOGGER.debug("closing idle connection")
            session.writer.close()

    @staticmethod
    async def _close_session(session: _Session) -> None:
        """Close a connection in good order, but wait at most `_CLOSE_TIMEOUT_SECONDS` for the acknowledgement."""
        session.writer.close()
        try:
            async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                await session.writer.wait_closed()
        except OSError:  # Includes TimeoutError.
            session.writer.transport.abort()

    @staticmethod
    def _abort_session(session: _Session) -> None:
        """Drop a connection at once, without waiting for anything. Nothing can hang here."""
        session.writer.transport.abort()
