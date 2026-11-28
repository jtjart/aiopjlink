"""Filter usage and replacement models (§4.20 FILT ?, §4.22 RFIL ?)."""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender


class Filter:
    """Status information about the projector filters (§4.20, §4.22).

    A projector without a filter raises `PJLinkNotSupportedError("no filter")`.
    """

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the filter status command handler."""
        self._sender = sender

    async def hours(self) -> int:
        """Query filter usage time (§4.20).

        Returns:
            Filter usage time in hours (0 if the projector does not count it).

        Raises:
            PJLinkUnexpectedValueError: The projector returned a value that is not an integer.
        """
        try:
            return int(await self._sender.query_status("FILT", PJClass.TWO, not_supported_message="no filter"))
        except ValueError as err:
            raise PJLinkUnexpectedValueError("filter usage not parsable") from err

    async def replacement_models(self) -> list[str]:
        """Get the filter replacement models listed in the projector (§4.22).

        Returns:
            The listed filter replacement model numbers.
        """
        models = await self._sender.transmit("RFIL", "?", PJClass.TWO)
        return [model for model in models.split(" ") if model]
