"""commands/lamp.py

Lamp status and replacement models (§4.8 LAMP ?, §4.21 RLMP ?).
"""

from enum import Enum

from ..enums import PJClass
from ..exceptions import (
    PJLinkERR1,
    PJLinkUnexpectedResponseParameter,
)
from .base import CommandGroup


class Lamp(CommandGroup):
    """Status information about the projector light sources (§4.8).

    According to the spec the "usage time of lamp is always 0 when it is
    not counted by the projector."
    """

    class State(Enum):
        OFF = "0"
        ON = "1"

    async def status(self) -> list[tuple[int, State]]:
        """Query the current lamp hours and lamp statuses.
        There may be more than one lamp in some projectors, so this is returned
        as a list.
        Returns:
            [(hours:int, state:Lamp.State)]: List of lamp hours and states for each lamp.
        """
        # Express a special meaning for ERR1 (§4.8).
        try:
            response = await self._link.transmit("LAMP", "?", pjclass=PJClass.ONE)
        except PJLinkERR1 as err:
            raise PJLinkERR1("no lamp") from err

        # Split the response by " " and then pair up all the numbers from
        # the list in groups of 2.  If there are any remainders, raise an error.
        # See: https://docs.python.org/3/library/itertools.html (grouper)
        # This takes a line like: "1000 1 50 0" and breaks it into pairs:
        #   (1000, 1), (50, 0)
        # Such that these can then be remapped into our high level interface.
        try:
            # Python 3.9 solution.
            pairs = []
            numbers = response.split(" ")
            for i in range(0, len(numbers), 2):
                pairs.append(numbers[i : i + 2])

            # Python 3.10 solution.
            # pairs = zip(*[iter(response.split(' '))] * 2, strict=True)
            # pairs = [pair for pair in pairs]#

            # Remap the statuses to integers and our lamp state enum.
            return [(int(hours), Lamp.State(state)) for hours, state in pairs]
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unparsable lamp status") from err

    async def hours(self) -> int:
        """How long has the first lamp been on (hour, integer).

        According to the spec (§4.8) the "usage time of lamp is always 0 when it is
        not counted by the projector."
        """
        return (await self.status())[0][0]

    async def replacement_models(self) -> list[str]:
        """Get the lamp replacement models listed in the projector.
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._link.transmit("RLMP", "?", pjclass=PJClass.TWO)
        return [m for m in models.split(" ") if m]
