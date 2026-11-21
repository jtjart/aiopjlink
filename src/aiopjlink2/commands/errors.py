"""Error status (§4.7 ERST ?)."""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender

_NUMBER_OF_ERROR_CATEGORIES = 6


class Errors:
    """Provide information about errors occurring within the projector (§4.7)."""

    class Category(Enum):
        """The different types of error returned according to (§4.7)."""

        FAN = "fan"
        LAMP = "lamp"
        TEMP = "temperature"
        COVER = "cover"
        FILTER = "filter"
        OTHER = "other"

    class Level(Enum):
        """Error level for each `Category` (§4.7)."""

        OK = "0"
        WARN = "1"
        ERROR = "2"

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the error status command handler."""
        self._sender = sender

    async def query(self) -> dict[Category, Level]:
        """Query the latest error level of each error category (§4.7).

        Returns:
            The `Errors.Level` of every `Errors.Category`.
        """
        return parse_error_levels(await self._sender.query_status("ERST", PJClass.ONE))


def parse_error_levels(levels_text: str) -> dict[Errors.Category, Errors.Level]:
    """Parse the six error levels of an `ERST` query response (§4.7) or status notification (§3.3.2)."""
    if len(levels_text) != _NUMBER_OF_ERROR_CATEGORIES:
        raise PJLinkUnexpectedValueError("unexpected number of error types reported")
    try:
        return {
            Errors.Category.FAN: Errors.Level(levels_text[0]),
            Errors.Category.LAMP: Errors.Level(levels_text[1]),
            Errors.Category.TEMP: Errors.Level(levels_text[2]),
            Errors.Category.COVER: Errors.Level(levels_text[3]),
            Errors.Category.FILTER: Errors.Level(levels_text[4]),
            Errors.Category.OTHER: Errors.Level(levels_text[5]),
        }
    except ValueError as err:
        raise PJLinkUnexpectedValueError("unknown error level") from err
