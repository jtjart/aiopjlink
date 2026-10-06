"""commands/information.py

Information queries (§4.10 NAME ?, §4.11 INF1 ?, §4.12 INF2 ?, §4.13 INFO ?,
§4.14 CLSS ?, §4.15 SNUM ?, §4.16 SVER ?).
"""

from collections.abc import Awaitable, Callable

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup


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
