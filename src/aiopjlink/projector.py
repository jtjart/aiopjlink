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
from collections.abc import Awaitable, Callable

from ._transport import Transport
from .commands.base import CommandGroup
from .commands.errors import Errors
from .commands.filter import Filter
from .commands.freeze import Freeze
from .commands.lamp import Lamp
from .commands.mute import Mute
from .commands.power import Power
from .commands.sources import Sources
from .commands.volume import Volume
from .enums import PJClass
from .exceptions import (
    PJLinkUnexpectedResponseParameter,
)


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


class Information(CommandGroup):
    """Gathers information about the projector."""

    async def table(self) -> dict[str, str | None]:
        """Collect a table of all the different information available
        from this projector.  If the projector responds, an empty string is
        returned, but if it throws an error, `None` is returned.

        See the code for the dictionary entries.
        """

        # Helper to ensure it is always returned regardless of the exception.
        async def _safe(method: Callable[[], Awaitable[str | PJClass]]) -> str | None:
            try:
                return str(await method())
            except Exception:
                return None

        # Table.
        return {
            "software_version": await _safe(self.software_version),
            "serial_number": await _safe(self.serial_number),
            "pjlink_class": await _safe(self.pjlink_class),
            "other": await _safe(self.other),
            "product_name": await _safe(self.product_name),
            "manufacturer_name": await _safe(self.manufacturer_name),
            "projector_name": await _safe(self.projector_name),
        }

    async def software_version(self) -> str:
        """Request software version of the projector (§4.16).
        The version information of the software defined by the manufacturer is indicated.
        Version information can be expressed in any way.

        Returns:
            str: The version string.
        """
        return await self._link.transmit("SVER", "?", PJClass.TWO)

    async def serial_number(self) -> str:
        """Request the projector serial number (§4.15).
        The serial number information defined by the manufacturer is indicated.

        Returns:
            str: The serial number string.
        """
        return await self._link.transmit("SNUM", "?", PJClass.TWO)

    async def pjlink_class(self, pjclass: PJClass = PJClass.ONE) -> PJClass:
        """Get projectors PJLink class number as a `PJClass` enumeration (§4.14)"""
        try:
            return PJClass(await self._link.transmit("CLSS", "?", pjclass=pjclass))
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected PJLink class") from err

    async def other(self) -> str:
        """Query the projector for other information about the projector/display
        described by the manufacture. Defined as in (§4.13).

        If there is no other information, this returns an empty string.
        """
        return await self._link.transmit("INFO", "?", PJClass.ONE)

    async def product_name(self) -> str:
        """Get product name information string (e.g. EPSON PU1007B/PU1007W) as in (§4.12).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("INF2", "?", PJClass.ONE)

    async def manufacturer_name(self) -> str:
        """Get manufacturer name information string (e.g. EPSON) as in (§4.11).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("INF1", "?", PJClass.ONE)

    async def projector_name(self) -> str:
        """Get projector name information string (e.g. EBB13648) as in (§4.10).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("NAME", "?", PJClass.ONE)
