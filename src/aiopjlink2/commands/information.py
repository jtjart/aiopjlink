"""Information queries (§4.10 NAME, §4.11 INF1, §4.12 INF2, §4.13 INFO, §4.14 CLSS, §4.15 SNUM, §4.16 SVER)."""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender


class Information:
    """Gathers information about the projector."""

    # The queries for free text use `transmit`, not `query_status`: unlike for a status, `OK` is a legitimate answer
    # there (a projector may be called "OK"). Only `CLSS` is a status.

    def __init__(self, sender: CommandSender) -> None:
        self._sender = sender

    async def software_version(self) -> str:
        """Request the software version of the projector (§4.16).

        The manufacturer decides how the version is written.

        Returns:
            The version string.
        """
        return await self._sender.transmit("SVER", "?", PJClass.TWO)

    async def serial_number(self) -> str:
        """Request the projector serial number (§4.15).

        The manufacturer decides how the serial number is written.

        Returns:
            The serial number string.
        """
        return await self._sender.transmit("SNUM", "?", PJClass.TWO)

    async def pjlink_class(self, pjclass: PJClass = PJClass.ONE) -> PJClass:
        """Get the PJLink class number of the projector as a `PJClass` (§4.14)."""
        try:
            return PJClass(await self._sender.query_status("CLSS", pjclass))
        except ValueError as err:
            raise PJLinkUnexpectedValueError("unexpected PJLink class") from err

    async def other_information(self) -> str:
        """Query the other information the manufacturer gives about the projector or display (§4.13).

        If there is no other information, this returns an empty string.
        """
        return await self._sender.transmit("INFO", "?", PJClass.ONE)

    async def product_name(self) -> str:
        """Get product name information string (e.g. EPSON PU1007B/PU1007W) as in (§4.12).

        If there is no information, this returns an empty string.
        """
        return await self._sender.transmit("INF2", "?", PJClass.ONE)

    async def manufacturer_name(self) -> str:
        """Get manufacturer name information string (e.g. EPSON) as in (§4.11).

        If there is no information, this returns an empty string.
        """
        return await self._sender.transmit("INF1", "?", PJClass.ONE)

    async def projector_name(self) -> str:
        """Get projector name information string (e.g. EBB13648) as in (§4.10).

        If there is no information, this returns an empty string.
        """
        return await self._sender.transmit("NAME", "?", PJClass.ONE)
