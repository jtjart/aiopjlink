"""client.py

The `PJLink` class is a connection to a projector using the PJLink protocol.

To provide a "pythonic" API for the different PJLink commands, the groups of
related commands in `aiopjlink.commands` build on `CommandGroup`.

The only state kept inside the classes is the connection to the projector and the lock
that serialises the commands sent through one `PJLink` object (see `aiopjlink._transport`
for how the connection is managed).

Error handling
--------------
See `aiopjlink.exceptions`: everything raised here is a subclass of `PJLinkException`.
"""

from ._transport import DEFAULT_IDLE_TIMEOUT, Transport
from .commands import Errors, Filter, Freeze, Information, Lamp, Mute, Power, Sources, Volume
from .enums import PJClass


class PJLink(Transport):
    """Manages a PJLink connection to a projector.

    The connection is opened by the first command, kept for the commands that follow
    and replaced by itself when the projector drops it (it does so after 30 seconds of
    silence). Call `close` when you are done, or use the object as an `async with` block.
    One object can safely be shared between several tasks: commands are sent one after
    the other.

    `idle_timeout` is how many seconds a kept connection waits for the next command before it
    is released (default 25, the projector drops it after 30). A projector that dislikes long
    sessions can be given a short one, e.g. 2: commands sent in quick succession (one poll) then
    share a connection, and it is closed right after.

    Some projectors cannot handle more than one command per connection. Pass
    `persistent=False` for those: every command then opens its own short-lived
    connection, and there is nothing to close.

    Every command is bound by `timeout` seconds in total, including connecting.

    Usage:

        >>> async with PJLink(address='192.168.100.100', password='secret') as link:
        ...     await link.power.turn_off()
        ...     await asyncio.sleep(4)
        ...     await link.power.turn_on()

    """

    C1 = PJClass.ONE
    C2 = PJClass.TWO

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
        super().__init__(address, port, password, timeout, encoding, persistent=persistent, idle_timeout=idle_timeout)

        # Add the different API namespaces.
        self.info: Information = Information(self)
        self.power: Power = Power(self)
        self.sources: Sources = Sources(self)
        self.mute: Mute = Mute(self)
        self.errors: Errors = Errors(self)
        self.lamps: Lamp = Lamp(self)
        self.filter: Filter = Filter(self)
        self.freeze: Freeze = Freeze(self)
        self.microphone: Volume = Volume(self, "MVOL")
        self.speaker: Volume = Volume(self, "SVOL")

    async def wait_for_notification(self) -> None:
        raise NotImplementedError("class 2 method not supported")
