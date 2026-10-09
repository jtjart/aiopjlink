"""commands/filter.py

Filter usage and replacement models (§4.20 FILT ?, §4.22 RFIL ?).
"""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup


class Filter(CommandGroup):
    """Status information about the projector filters (§4.20, §4.22)."""

    async def hours(self) -> int:
        """Query the filter usage time (§4.20).
        Filter usage time is always 0 when it is not counted by the projector.
        """
        try:
            return int(await self._transmit_state("FILT", PJClass.TWO, err1="no filter"))
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("filter usage not parsable") from err

    async def replacement_models(self) -> list[str]:
        """Get the filter replacement models listed in the projector (§4.22).
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._link.transmit("RFIL", "?", pjclass=PJClass.TWO)
        return [m for m in models.split(" ") if m]
