"""client.py

The `PJLink` class is a connection to a projector using the PJLink protocol.

To provide a "pythonic" API for the different PJLink commands, `PJLink` owns one
`Transport` and gives every group of related commands in `aiopjlink.commands` a
`CommandSender` on top of it.

The only state kept inside the classes is the connection to the projector and the lock
that serialises the commands sent through one `PJLink` object (see `aiopjlink._transport`
for how the connection is managed).

Error handling
--------------
See `aiopjlink.exceptions`: everything raised here is a subclass of `PJLinkException`.
"""

from types import TracebackType
from typing import Self

from ._transport import DEFAULT_IDLE_TIMEOUT_SECONDS, Transport
from .commands import Errors, Filter, Freeze, Information, Lamp, Mute, Power, Sources, Volume
from .commands._sender import CommandSender
from .enums import PJAuth, PJClass


class PJLink:
    """Manages a PJLink connection to a projector.

    The connection is opened by the first command, kept for the commands that follow
    and replaced by itself when the projector drops it (it does so after 30 seconds of
    silence). Call `close` when you are done, or use the object as an `async with` block.
    One object can safely be shared between several tasks: commands are sent one after
    the other.

    `idle_timeout_seconds` is how long a kept connection waits for the next command before it
    is released (default 25, the projector drops it after 30). A projector that dislikes long
    sessions can be given a short one, e.g. 2: commands sent in quick succession (one poll) then
    share a connection, and it is closed right after.

    Some projectors cannot handle more than one command per connection. Pass
    `persistent=False` for those: every command then opens its own short-lived
    connection, and there is nothing to close.

    `encoding` is the character encoding of the text exchanged with the projector (names, versions, ...).
    The spec prescribes UTF-8, the default. Bytes in a response that cannot be decoded are replaced
    with U+FFFD instead of failing, so a name in another encoding is still readable; pass the projector's
    encoding (e.g. `"latin-1"`) to get it exactly.

    Every command is bound by `timeout_seconds` in total, including connecting. The exception is a command
    that carries a password: a projector answers a wrong password only after two seconds (§5.1), so such a command
    is given at least 3 seconds to be answered, and a wrong password is reported as `PJLinkPassword`
    instead of `PJLinkNoConnection`, whatever `timeout_seconds` is.

    `authentication` chooses the password procedure (§5.1) for a projector that has security on. The default,
    `PJAuth.AUTO`, asks for SHA256 (specification 2.10) and uses MD5 for projectors that do not support it;
    `PJAuth.SHA256` never uses MD5 (a projector without SHA256 raises `PJLinkNotSupported`), and `PJAuth.MD5` never
    asks for SHA256. See the README for how a projector without SHA256 is recognised.

    Usage:

        >>> async with PJLink(address='192.168.100.100', password='secret') as link:
        ...     await link.power.turn_off()
        ...     await asyncio.sleep(4)
        ...     await link.power.turn_on()

    """

    C1 = PJClass.ONE
    C2 = PJClass.TWO

    def __init__(  # noqa: PLR0913
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
        self._transport = Transport(
            address,
            port,
            password,
            timeout_seconds,
            encoding,
            persistent=persistent,
            idle_timeout_seconds=idle_timeout_seconds,
            authentication=authentication,
        )

        # Add the different API namespaces, all of them talking through the same transport.
        sender = CommandSender(self._transport)
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
        return self._transport.persistent

    @property
    def authentication(self) -> PJAuth:
        """The authentication this object was asked to use (`PJAuth.AUTO` unless set otherwise)."""
        return self._transport.authentication

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
        await self._transport.close()
