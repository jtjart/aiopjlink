"""commands/filter.py

Filter usage and replacement models (§4.20 FILT ?, §4.22 RFIL ?).
"""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from ._sender import CommandSender


class Filter:
    """Status information about the projector filters (§4.20, §4.22)."""

    def __init__(self, sender: CommandSender) -> None:
        self._sender = sender

    async def hours(self) -> int:
        """Query the filter usage time (§4.20).
        Filter usage time is always 0 when it is not counted by the projector.
        """
        try:
            return int(await self._sender.query_status("FILT", PJClass.TWO, not_supported_message="no filter"))
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("filter usage not parsable") from err

    async def replacement_models(self) -> list[str]:
        """Get the filter replacement models listed in the projector (§4.22).
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._sender.transmit("RFIL", "?", PJClass.TWO)
        return [model for model in models.split(" ") if model]
