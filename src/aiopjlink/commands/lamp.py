"""commands/lamp.py

Lamp status and replacement models (§4.8 LAMP ?, §4.21 RLMP ?).
"""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
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

        There may be more than one lamp in some projectors, so this is returned as a list.

        Returns:
            A list of ``(hours, state)`` tuples for each lamp.
        """
        response = await self._transmit_state("LAMP", PJClass.ONE, err1="no lamp")

        try:
            values = response.split()
            if not values:
                raise ValueError("empty lamp status")
            pairs = zip(values[::2], values[1::2], strict=True)
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
