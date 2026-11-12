"""commands/errors.py

Error status (§4.7 ERST ?).
"""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup

_NUMBER_OF_ERROR_CATEGORIES = 6


class Errors(CommandGroup):
    """Provide information about errors occuring within the projector (§4.7)."""

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

    async def query(self) -> dict[Category, Level]:
        """Query the projecteor for the latest error status
        information for each of the error categories (§4.7).

        Returns:
            dict[Category]: Level: Table of error categories to states.
        """
        return parse_error_levels(await self._query_status("ERST", PJClass.ONE))


def parse_error_levels(levels_text: str) -> dict[Errors.Category, Errors.Level]:
    """Parse the six error levels of an `ERST` query response (§4.7) or status notification (§3.3.2)."""
    if len(levels_text) != _NUMBER_OF_ERROR_CATEGORIES:
        raise PJLinkUnexpectedResponseParameter("unexpected number of error types reported")
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
        raise PJLinkUnexpectedResponseParameter("unknown error level") from err
