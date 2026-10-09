"""commands/errors.py

Error status (§4.7 ERST ?).
"""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup


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
        errors = await self._transmit_state("ERST", PJClass.ONE)
        if len(errors) != 6:
            raise PJLinkUnexpectedResponseParameter("unexpected number of error types reported")
        try:
            return {
                Errors.Category.FAN: Errors.Level(errors[0]),
                Errors.Category.LAMP: Errors.Level(errors[1]),
                Errors.Category.TEMP: Errors.Level(errors[2]),
                Errors.Category.COVER: Errors.Level(errors[3]),
                Errors.Category.FILTER: Errors.Level(errors[4]),
                Errors.Category.OTHER: Errors.Level(errors[5]),
            }
        except IndexError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected number of error types reported") from err
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unknown error level") from err
