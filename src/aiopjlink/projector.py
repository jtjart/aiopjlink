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
from .commands.lamp import Lamp
from .commands.mute import Mute
from .commands.power import Power
from .commands.sources import Sources
from .enums import PJClass
from .exceptions import (
    PJLinkERR1,
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


class Filter(CommandGroup):
    """Status information about the projector filters (§4.20, §4.22)."""

    async def hours(self) -> int:
        """Query the filter usage time (§4.20).
        Filter usage time is always 0 when it is not counted by the projector.
        """
        # Request the value.
        try:
            return int(await self._link.transmit("FILT", "?", pjclass=PJClass.TWO))

        # Express a special meaning for ERR1 (§4.20).
        except PJLinkERR1 as err:
            raise PJLinkERR1("no filter") from err

        # Parse issue.
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("filter usage not parsable") from err

    async def replacement_models(self) -> list[str]:
        """Get the filter replacement models listed in the projector (§4.22).
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._link.transmit("RFIL", "?", pjclass=PJClass.TWO)
        return [m for m in models.split(" ") if m]


class Freeze(CommandGroup):
    """Controls freezing and unfreezing the current frame (§4.25, §4.26)."""

    async def set(self, freeze: bool) -> None:
        """Freeze or unfreeze the screen (§4.25)."""
        cmd = "1" if bool(freeze) else "0"
        await self._transmit_ok("FREZ", cmd, pjclass=PJClass.TWO)

    async def get(self) -> bool:
        """Returns True if the screen is currently frozen, and False if not §4.26."""
        response = await self._link.transmit("FREZ", "?", pjclass=PJClass.TWO)
        if response == "0":
            return False
        if response == "1":
            return True
        raise PJLinkUnexpectedResponseParameter("unexpected freeze state")


class Volume(CommandGroup):
    """Controls a xVOL style command (e.g. for speakers and microphones) as
    defined in (§4.23, §4.24).

    According to the spec:
        "As for a specification to increase the microphone volume by one level when it
        is in the maximum state, and a specification to decrease the microphone
        volume by one level when it is in the minimum state, the response
        for a normal case is returned."

    Volume related to audio output (audio out, built-in speaker in equipment
    model, etc.) is referred to as the speaker volume.

    Volume related to voice input (audio in, microphone terminal to be input
    to the model, etc.) is referred to as the microphone volume.
    """

    def __init__(self, link: PJLink, instruction: str) -> None:
        super().__init__(link)
        self.instruction = instruction

    async def turn_up(self) -> None:
        """Increase the volume by one unit."""
        await self._transmit_ok(self.instruction, "1", pjclass=PJClass.TWO)

    async def turn_down(self) -> None:
        """Decrease the volume by one unit."""
        await self._transmit_ok(self.instruction, "0", pjclass=PJClass.TWO)


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
