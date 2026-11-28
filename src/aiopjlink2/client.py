"""The `PJLink` class is a connection to a projector using the PJLink protocol.

To provide a "pythonic" API for the different PJLink commands, `PJLink` hands every group of related commands in
`aiopjlink2.commands` a `CommandSender` that sends through `PJLink._transmit`. The groups are given that function,
not the `PJLink` object, so `aiopjlink2.commands` never imports this module.

Connection handling
-------------------
The spec lets a controller send any number of commands on one TCP connection as
long as each follows the previous answer within 30 seconds (§5.3), and it says the
authentication data may be left out after the first command. The projector drops a
connection that stays silent for 30 seconds (§5.4, §6).

By default (`persistent=True`) a `PJLink` therefore keeps the connection of the last
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
`PJLinkAuthenticationError`, not as a dead connection, so such a command is given at least
`_MINIMUM_DIGEST_ANSWER_SECONDS` to be answered, whatever `timeout_seconds` is.

Error handling
--------------
See `aiopjlink2.exceptions`: everything raised here is a subclass of `PJLinkError`.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import NoReturn, Self

from ._auth import (
    SHA256_INQUIRY,
    authentication_required,
    build_md5_request,
    build_sha256_request,
    parse_security_reply,
)
from ._debug import LOGGER, redact_debug_payload
from ._protocol import PJCommand, parse_response
from .commands import Errors, Filter, Freeze, Information, Lamp, Mute, Power, Sources, Volume
from .commands._sender import CommandSender
from .enums import PJAuth, PJClass
from .exceptions import (
    PJLinkAuthenticationError,
    PJLinkConnectionClosedError,
    PJLinkError,
    PJLinkNoConnectionError,
    PJLinkNotSupportedError,
    PJLinkProjectorError,
    PJLinkProtocolError,
)

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


class _Phase(Enum):
    """Where a connection is in a command. A timeout reports it, and `IDLE` says the connection can be reused.

    The value of every phase but `IDLE` is the message of the timeout that happens in it.
    """

    IDLE = ""
    CONNECT = "timeout - projector did not accept the connection in time"
    GREETING = "timeout - projector did not send a welcome message in time"
    SECURITY = "timeout - projector did not complete the security handshake in time"
    SEND = "timeout - projector did not accept the command in time"
    RESPONSE = "timeout - projector did not respond in time"


class _Md5RejectedError(Exception):
    """MD5 was rejected by a projector that may still do SHA256: send the command again, asking for SHA256.

    Raised by `PJLink._reject_password`, caught by `PJLink._transmit`. It is not a `PJLinkError` on purpose:
    it is never visible outside this module, and must not be caught by an `except PJLinkAuthenticationError`.
    """


@dataclass(slots=True)
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

    phase: _Phase = _Phase.GREETING
    """What the connection is waiting for. Anything but `IDLE` when a command ends means: do not reuse it."""

    sha256_declined: bool = False
    """True if the projector answered the SHA256 question with something but yes (silence does not count)."""

    @property
    def usable(self) -> bool:
        """False once the projector or the network has closed the connection."""
        return not (self.writer.is_closing() or self.reader.at_eof() or self.reader.exception() is not None)


class PJLink:
    """Manages a PJLink connection to a projector.

    The connection is opened by the first command, reused for the next ones and replaced by itself when the
    projector drops it (it does so after 30 seconds of silence). Call `close` when you are done, or use the object
    as an `async with` block. One object can be shared between tasks: commands are sent one after the other.

    Every command raises a subclass of `PJLinkError` when talking to the projector fails, and `ValueError` for an
    invalid argument, in which case nothing is sent. See `exceptions.py`.

    The commands are grouped by feature, one attribute for each: `power`, `sources`, `mute`, `errors`, `lamps`,
    `filter`, `freeze`, `speaker`, `microphone` and `info`.

    Usage:

        >>> async with PJLink(address='192.168.100.100', password='secret') as link:
        ...     await link.power.turn_off()
        ...     await asyncio.sleep(4)
        ...     await link.power.turn_on()

    """

    def __init__(  # ruff: ignore[too-many-arguments]
        self,
        address: str,
        port: int = 4352,
        password: str | None = None,
        timeout_seconds: float = 4,
        encoding: str = "utf-8",
        *,
        persistent: bool = True,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        authentication: PJAuth = PJAuth.AUTO,
    ) -> None:
        """Initialize a PJLink client.

        Args:
            address: Projector IP address or host name.
            port: Projector TCP port.
            password: Password, if the projector requires authentication.
            timeout_seconds: Command deadline, including connection setup. A wrong password is reported as
                `PJLinkAuthenticationError`, not a timeout.
            encoding: Encoding for command and response text. Undecodable response bytes are
                replaced with U+FFFD.
            persistent: Reuse the connection between commands. When False, `close()` is a no-op and each command
                uses its own connection.
            idle_timeout_seconds: How long to keep an idle connection open. The projector closes it after 30
                seconds; a value around 2 gives one connection per poll.
            authentication: Password procedure: negotiates SHA256 and falls back to MD5;
                `PJAuth.SHA256` never falls back, and `PJAuth.MD5` skips SHA256 negotiation.

        Raises:
            ValueError: `idle_timeout_seconds` is not positive.
        """
        if idle_timeout_seconds <= 0:
            raise ValueError(
                "idle_timeout_seconds must be positive (use persistent=False for one connection per command)"
            )
        self._address = address
        self._port = port
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._encoding = encoding
        self._persistent = persistent
        self._idle_timeout_seconds = idle_timeout_seconds
        self._authentication = authentication

        # One command at a time: many projectors only accept a single connection, and the
        # answer to a command must not be mixed up with the answer to another one.
        self._command_lock = asyncio.Lock()

        # The connection to the projector: kept between commands, and the one a command uses while it runs.
        # It is only replaced with the command lock held. The idle timer, which does not take the lock, is
        # cancelled when a command starts and only set when one ends.
        self._session: _Session | None = None
        self._idle_close_timer: asyncio.TimerHandle | None = None

        # True once the projector has answered a command we sent a password digest with.
        self._password_accepted = False

        # The procedure the projector last accepted a password with (`PJAuth.SHA256` or `PJAuth.MD5`), if any.
        # Only a success is remembered: a silent projector may just be having a bad moment.
        self._learned_authentication_method: PJAuth | None = None

        sender = CommandSender(self._transmit)
        self.info: Information = Information(sender)
        self.power: Power = Power(sender)
        self.sources: Sources = Sources(sender)
        self.mute: Mute = Mute(sender)
        self.errors: Errors = Errors(sender)
        self.lamps: Lamp = Lamp(sender)
        self.filter: Filter = Filter(sender)
        self.freeze: Freeze = Freeze(sender)
        self.microphone: Volume = Volume(sender, "MVOL")
        self.speaker: Volume = Volume(sender, "SVOL")

    @property
    def persistent(self) -> bool:
        """True if the connection is kept open and reused, False if every command opens its own."""
        return self._persistent

    @property
    def authentication(self) -> PJAuth:
        """The authentication this object was asked to use (`PJAuth.AUTO` unless set otherwise)."""
        return self._authentication

    async def __aenter__(self) -> Self:
        """Return this client for use as an async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Close the client when leaving an async context manager block."""
        await self.close()

    async def close(self) -> None:
        """Close the connection kept for reuse, if there is one.

        Safe to call at any time and more than once. A command that is still running
        finishes first (it is bounded by `timeout_seconds`). The object stays usable: the next
        command simply connects again. Does nothing if `persistent` is False.
        """
        async with self._command_lock:
            self._cancel_idle_timer()
            session, self._session = self._session, None
            if session is not None:
                await self._close_session(session)

    async def _read_line(self, reader: asyncio.StreamReader) -> str:
        """Read the next CR-terminated message.

        Returns:
            The decoded line including its CR terminator.

        Raises:
            PJLinkConnectionClosedError: The projector closes or loses the connection.
            PJLinkProtocolError: The response line is longer than the protocol limit.
        """
        try:
            raw_line = await reader.readuntil(b"\r")
        except asyncio.IncompleteReadError as err:
            raise PJLinkConnectionClosedError("projector closed the connection") from err
        except asyncio.LimitOverrunError as err:
            raise PJLinkProtocolError("response from projector is too long") from err
        except OSError as err:
            raise PJLinkConnectionClosedError(f"connection error - {err}") from err

        # The spec prescribes UTF-8, but free text (a projector name, say) does turn up in other encodings. That must
        # not make the whole answer unreadable: undecodable bytes become U+FFFD. The fields that are not free text are
        # validated by their parsers anyway, so garbage still ends up as an error there.
        return raw_line.decode(self._encoding, errors="replace").lstrip("\n")

    async def _transmit(self, command: PJCommand) -> str:
        """Send one command, authenticating and connecting first if needed.

        Calls are serialised, so this can be used from several tasks at once. The whole call, from connecting
        to the answer, is bound by `timeout_seconds`.

        Returns:
            The response parameter.

        Raises:
            PJLinkError: The command fails while connecting, authenticating, communicating, or parsing a response.
        """
        async with self._command_lock:
            try:
                return await self._attempt_transmit(command)
            except _Md5RejectedError:
                LOGGER.debug("MD5 was rejected by a projector that may do SHA256, asking again")
            # The rejected command was not carried out, so asking again is safe even for a command that changes
            # something. The second try is for SHA256 only, so a wrong password is not rejected twice, and it has
            # a deadline of its own: the first try ended with an answer, so the projector is there.
            return await self._attempt_transmit(command, sha256_only=True)

    async def _attempt_transmit(self, command: PJCommand, *, sha256_only: bool = False) -> str:
        """Run one transmission attempt. Must only be called with the lock held.

        The try is bound by `timeout_seconds` (but see `_MINIMUM_DIGEST_ANSWER_SECONDS`). A SHA256-only attempt is
        used after a rejected MD5 digest and does not fall back to another authentication method.

        Returns:
            The response parameter.
        """
        self._prepare_session()
        try:
            async with asyncio.timeout(self._timeout_seconds) as deadline:
                session, response_line = await self._send_until_answered(command, deadline, sha256_only=sha256_only)
                return self._parse_answer(session, response_line, command.name, command.pjclass)
        except TimeoutError as err:
            raise self._timeout_error(sha256_only=sha256_only) from err
        finally:
            await self._release_session()

    def _timeout_error(self, *, sha256_only: bool) -> PJLinkError:
        """Choose the error for an expired command deadline.

        Returns:
            `PJLinkNoConnectionError` naming the phase the command was waiting in, or `PJLinkAuthenticationError` if
            a SHA256-only retry timed out on its digest (§5.1).
        """
        session = self._session
        if session is None:
            return PJLinkNoConnectionError(_Phase.CONNECT.value)
        if sha256_only and session.phase is _Phase.RESPONSE and session.digest_sent:
            # MD5 was rejected before, and now the projector sits on our SHA256 digest: a projector that dislikes
            # a digest answers only after two seconds (§5.1). The password is wrong, not the connection.
            return PJLinkAuthenticationError("authentication failed")
        return PJLinkNoConnectionError(session.phase.value)

    async def _send_until_answered(
        self, command: PJCommand, deadline: asyncio.Timeout, *, sha256_only: bool
    ) -> tuple[_Session, str]:
        """Send the command and read the line that answers it: on the kept connection if there is one, else a new one.

        A query retries on a new connection if the kept one is dead. A command that changes state does not,
        because the projector may have carried it out before disconnecting.

        Returns:
            The session and response line.

        Raises:
            PJLinkConnectionClosedError: The reused connection closes while handling a non-query command.
        """
        kept_session = self._session
        if kept_session is not None:
            try:
                # Whatever is waiting on a kept connection is not the answer to this command.
                await self._discard_unsolicited(kept_session)
                return kept_session, await self._send_and_read(kept_session, command.line, deadline)
            except PJLinkConnectionClosedError:
                if not command.is_query:
                    raise
                LOGGER.debug("reused connection was closed by the projector, reconnecting")
                self._drop_session(kept_session)

        session = await self._connect(deadline, sha256_only=sha256_only)
        return session, await self._send_and_read(session, command.line, deadline)

    async def _connect(self, deadline: asyncio.Timeout, *, sha256_only: bool) -> _Session:
        """Open a connection that is ready for its first command (§5.1).

        A projector that wants a password is asked whether it supports SHA256. Otherwise, a new connection is
        opened for MD5. `sha256_only` is the second try after MD5 was rejected, so it must not fall back.

        Returns:
            A connected PJLink session ready for its first command.

        Raises:
            PJLinkAuthenticationError: The retry after a rejected MD5 digest finds that the projector does not support
                SHA256, so the password was wrong.
            PJLinkNotSupportedError: SHA256 authentication is not supported by the projector.
        """
        session = await self._open_greeted_session()
        if not (sha256_only or self._should_ask_for_sha256()):
            return session

        session.phase = _Phase.SECURITY
        sha256_supported = await self._negotiate_sha256(session, deadline)
        if sha256_supported is True:
            return session

        self._drop_session(session)
        if self._authentication is PJAuth.SHA256:
            raise PJLinkNotSupportedError("SHA256 authentication not supported by the projector")
        if sha256_only:
            # The first try had its MD5 digest rejected, and the projector does not say yes to SHA256 either.
            raise PJLinkAuthenticationError("authentication failed")
        # Assumed from now on, even if the new connection fails: a projector that cannot cope with the question
        # must not be asked again by every connection. If it was a SHA256 projector that missed it, the rejected
        # MD5 digest puts that right.
        self._learned_authentication_method = PJAuth.MD5
        LOGGER.debug("projector does not support SHA256, reconnecting to use MD5")
        session = await self._open_greeted_session()
        session.sha256_declined = sha256_supported is False
        return session

    async def _open_greeted_session(self) -> _Session:
        """Open a connection and read the welcome line the projector sends first, to identify itself as PJLINK.

        Returns:
            The connected session with its greeting line.

        Raises:
            PJLinkNoConnectionError: TCP connection setup fails.
        """
        try:
            reader, writer = await asyncio.open_connection(self._address, self._port)
        except OSError as err:
            raise PJLinkNoConnectionError(f"connection failed - {err}") from err
        LOGGER.debug("connected to %s:%s", self._address, self._port)
        session = _Session(reader, writer)
        # From here on, however the command ends, `_release_session` keeps or drops this connection.
        self._session = session

        session.greeting = await self._read_line(session.reader)
        LOGGER.debug("received welcome/authentication message")
        return session

    async def _send_and_read(self, session: _Session, command_line: str, deadline: asyncio.Timeout) -> str:
        """Send the command line, with the authentication data in front if it is the first one, and read the answer.

        Returns:
            The response line from the projector.

        Raises:
            PJLinkAuthenticationError: The projector closes the connection after receiving a password digest.
            PJLinkConnectionClosedError: The connection closes before a complete answer is received.
        """
        session.phase = _Phase.SEND
        await self._send(session, command_line)
        if session.digest_sent:
            self._allow_time_to_reject_digest(deadline)

        session.phase = _Phase.RESPONSE
        try:
            return await self._read_line(session.reader)
        except PJLinkConnectionClosedError as err:
            if not session.digest_sent or self._password_accepted:
                raise
            raise PJLinkAuthenticationError(
                "projector closed the connection after the password was sent - the password is probably wrong"
            ) from err

    @staticmethod
    def _allow_time_to_reject_digest(deadline: asyncio.Timeout) -> None:
        """A projector that dislikes the digest answers only after two seconds (§5.1).

        That wait must not use up the deadline, or a wrong password would look like a dead connection.
        """
        deadline_time = deadline.when()
        if deadline_time is None:
            return
        deadline.reschedule(max(deadline_time, asyncio.get_running_loop().time() + _MINIMUM_DIGEST_ANSWER_SECONDS))

    def _parse_answer(self, session: _Session, response_line: str, command: str, pjclass: PJClass) -> str:
        """Validate the response and authentication result.

        Returns:
            The parsed response parameter.

        Raises:
            PJLinkProjectorError: The projector returned an ERR1-ERR4 response.
            _Md5RejectedError: The rejected MD5 digest may be retried with SHA256.
        """
        if response_line.upper() == "PJLINK ERRA\r":
            self._reject_password(session)
        if session.digest_sent:
            self._password_accepted = True
            self._learned_authentication_method = session.authentication_method

        try:
            _, response_parameter = parse_response(response_line, expect_command=command, expect_pjclass=pjclass)
        except PJLinkProjectorError:
            # The projector answered, with an error: the answer was read completely.
            session.phase = _Phase.IDLE
            raise
        session.phase = _Phase.IDLE
        return response_parameter

    def _reject_password(self, session: _Session) -> NoReturn:
        """The projector answered a digest with `ERRA`.

        Raises:
            _Md5RejectedError: MD5 was rejected and the client should retry with SHA256.
            PJLinkAuthenticationError: The digest was rejected and no SHA256 retry is appropriate.
        """
        md5_was_used = session.authentication_method is PJAuth.MD5
        if md5_was_used and self._learned_authentication_method is PJAuth.MD5:
            # MD5 worked before and does not any more (the projector may have been switched to
            # SHA256, or the password changed): do not take it for granted any longer.
            self._learned_authentication_method = None
        if md5_was_used and self._authentication is PJAuth.AUTO and not session.sha256_declined:
            # The projector never said it does not do SHA256: ask again (see `_transmit`).
            raise _Md5RejectedError
        raise PJLinkAuthenticationError("authentication failed")

    def _should_ask_for_sha256(self) -> bool:
        """Decide whether a new connection should ask the projector for SHA256 (§5.1).

        Returns:
            True unless MD5 is forced, or MD5 is already known to work in AUTO mode.
        """
        if self._authentication is PJAuth.MD5:
            return False
        return not (self._authentication is PJAuth.AUTO and self._learned_authentication_method is PJAuth.MD5)

    async def _negotiate_sha256(self, session: _Session, deadline: asyncio.Timeout) -> bool | None:
        """Ask a projector that wants a password whether it supports SHA256 (§5.1).

        `ERRA` here is an answer to the security-level question, not a password error. Anything short of
        `PJLINK 2 <random number>` makes the controller use MD5: an error response or echo means SHA256 is declined;
        hanging up or silence means the projector did not answer. The tri-state distinguishes an answer (False)
        from silence (None), which proves little about what the projector supports.

        Returns:
            True when SHA256 is supported, False when it is declined, or None when the projector does not answer.

        Raises:
            PJLinkProtocolError: The welcome line is not a valid PJLink greeting.
        """
        if session.greeting is None or not authentication_required(session.greeting) or self._password is None:
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
        except (TimeoutError, PJLinkConnectionClosedError, PJLinkProtocolError, OSError):
            LOGGER.debug("no answer to the security level inquiry")
            return None

        projector_nonce = parse_security_reply(security_reply)
        if projector_nonce is None:
            LOGGER.debug("security level inquiry answered with: %s", redact_debug_payload(security_reply.strip()))
            return False
        session.sha256_nonce = projector_nonce
        return True

    async def _send(self, session: _Session, command_line: str) -> None:
        """Send a command line, with the authentication data in front if this is the first one (§5.1, §5.3).

        Raises:
            PJLinkConnectionClosedError: Writing to or draining the socket fails.
            PJLinkProtocolError: The greeting is not a valid PJLink greeting.
            PJLinkAuthenticationError: The greeting requires a password that was not supplied.
        """
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
            raise PJLinkConnectionClosedError(f"connection error - {err}") from err

    @staticmethod
    async def _discard_unsolicited(session: _Session) -> None:
        """Throw away what the projector sent while no command was waiting for an answer. Never waits for more.

        Raises:
            PJLinkConnectionClosedError: Reading from the socket fails.
        """
        try:
            async with asyncio.timeout(0):  # Reads what has arrived already; if there is none, gives up at once.
                unsolicited_bytes = await session.reader.read(_DISCARD_CHUNK_SIZE_BYTES)
        except TimeoutError:  # Before OSError, which it is a subclass of.
            return
        except OSError as err:
            raise PJLinkConnectionClosedError(f"connection error - {err}") from err
        if unsolicited_bytes:
            LOGGER.debug("discarded unsolicited data from the projector: %r", unsolicited_bytes)

    def _prepare_session(self) -> None:
        """A command starts: the kept connection, if it is still good, is in use from now on."""
        self._cancel_idle_timer()
        session = self._session
        if session is None:
            return
        if not session.usable:
            LOGGER.debug("kept connection is gone")
            self._drop_session(session)
            return
        # Not `IDLE` until the command has been answered, so that whatever happens in between
        # (a timeout, a cancellation) the connection is not kept.
        session.phase = _Phase.SEND

    async def _release_session(self) -> None:
        """Finish with the connection after a command.

        It is kept only if the last answer was read completely. Otherwise it is thrown away:
        a late answer to this command must never be taken for the answer to the next one.
        """
        session = self._session
        if session is None:
            return
        if session.phase is not _Phase.IDLE:
            self._drop_session(session)
        elif self._persistent:
            self._idle_close_timer = asyncio.get_running_loop().call_later(
                self._idle_timeout_seconds, self._close_idle_session, session
            )
        else:
            self._session = None
            await self._close_session(session)

    def _drop_session(self, session: _Session) -> None:
        """Drop the connection at once, without waiting for anything. Nothing can hang here."""
        if self._session is session:
            self._session = None
        session.writer.transport.abort()

    def _cancel_idle_timer(self) -> None:
        """Stop the timer that releases a connection nobody uses."""
        if self._idle_close_timer is not None:
            self._idle_close_timer.cancel()
            self._idle_close_timer = None

    def _close_idle_session(self, session: _Session) -> None:
        """Timer callback: nothing was sent for `idle_timeout_seconds`, so let go of the projector."""
        if self._session is not session:
            return

        self._idle_close_timer = None
        self._session = None
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
