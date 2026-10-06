"""projector.py

The `PJLink` class is a connection to a projector using the PJLink protocol.

To provide a "pythonic" API for the different PJLink commands, the
class `CommandGroup` is overriden and groups together related commands.

No state is kept inside the classes (apart from the lock that serialises
the commands sent through one `PJLink` object).

Error handling
--------------
See `aiopjlink.exceptions`: everything raised here is a subclass of `PJLinkException`.
"""

import asyncio

from ._transport import Transport
from .commands.errors import Errors
from .commands.filter import Filter
from .commands.freeze import Freeze
from .commands.information import Information
from .commands.lamp import Lamp
from .commands.mute import Mute
from .commands.power import Power
from .commands.sources import Sources
from .commands.volume import Volume
from .enums import PJClass


class PJLink(Transport):
    """Manages a PJLink connection to a projector.

    Every command opens its own short-lived connection, so there is nothing to
    open or close. One object can safely be shared between several tasks:
    commands are sent one after the other.

    Usage:

        >>> link = PJLink(address='192.168.100.100', password='secret')
        >>> await link.power.turn_off()
        >>> await asyncio.sleep(4)
        >>> await link.power.turn_on()

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
    ) -> None:
        super().__init__(address, port, password, timeout, encoding)

        # One command at a time: many projectors only accept a single connection.
        self._lock = asyncio.Lock()

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
