"""Control and query the projector's power state (§4.1 POWR, §4.2 POWR ?)."""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender


class Power:
    """Control and query the power state of the projector lamp."""

    class State(Enum):
        """PJLink projector lamp states (combining §4.1 and §4.2)."""

        OFF = "0"
        ON = "1"
        COOLING = "2"
        WARMING = "3"

        def __bool__(self) -> bool:
            """Tell whether the lamp is on or warming.

            Returns:
                True for ON and WARMING, False for OFF and COOLING.
            """
            return self in {Power.State.ON, Power.State.WARMING}

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the power command handler."""
        self._sender = sender

    async def set(self, state: State, pjclass: PJClass = PJClass.ONE) -> None:
        """Set the projector lamp power state.

        Args:
            state: The requested state; only `ON` and `OFF` can be set.

        Raises:
            ValueError: `state` is `COOLING` or `WARMING`; no command is sent.
        """
        if state in {Power.State.COOLING, Power.State.WARMING}:
            raise ValueError("expected Power.State.ON or Power.State.OFF")
        await self._sender.transmit_expecting_ok("POWR", state.value, pjclass=pjclass)

    async def get(self, pjclass: PJClass = PJClass.ONE) -> State:
        """Request the power status of the projector.

        Returns:
            The projector lamp power state.

        Raises:
            PJLinkUnexpectedValueError: The projector returned an unknown power state.
        """
        response_parameter = await self._sender.query_status("POWR", pjclass)
        try:
            return Power.State(response_parameter)
        except ValueError as err:
            raise PJLinkUnexpectedValueError("unexpected power state") from err

    async def turn_on(self) -> None:
        """Power the projector on."""
        await self.set(Power.State.ON)

    async def turn_off(self) -> None:
        """Power the projector off."""
        await self.set(Power.State.OFF)
