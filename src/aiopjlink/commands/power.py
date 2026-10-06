"""commands/power.py

Control and query the projector's power state (§4.1 POWR, §4.2 POWR ?).
"""

from enum import Enum

from ..enums import PJClass
from ..exceptions import (
    PJLinkUnexpectedResponseParameter,
)
from .base import CommandGroup


class Power(CommandGroup):
    """Control and query the power state of the projector lamp."""

    class State(Enum):
        """PJLink projector lamp states (combining §4.1 and §4.2)."""

        OFF = "0"
        ON = "1"
        COOLING = "2"
        WARMING = "3"

        def __bool__(self) -> bool:
            """Truthy states for `on` and `warming`, falsy states for `off` and `cooling`."""
            return self in (Power.State.ON, Power.State.WARMING)

    ON = State.ON
    OFF = State.OFF

    async def set(self, state: State, pjclass: PJClass = PJClass.ONE) -> None:
        """Send a power control instruction to power the projector lamp on or off."""
        state = Power.State(state)
        if state in (Power.State.COOLING, Power.State.WARMING):
            raise ValueError("expected Power.State.ON or Power.State.OFF")
        await self._transmit_ok("POWR", state.value, pjclass=pjclass)

    async def get(self, pjclass: PJClass = PJClass.ONE) -> State:
        """Request the power status of the projector."""
        response = await self._link.transmit("POWR", "?", pjclass=pjclass)
        try:
            return Power.State(response)
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected power state") from err

    async def turn_on(self) -> None:
        """Power the projector on."""
        await self.set(Power.State.ON)

    async def turn_off(self) -> None:
        """Power the projector off."""
        await self.set(Power.State.OFF)
