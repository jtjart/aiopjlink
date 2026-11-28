"""Lamp status and replacement models (§4.8 LAMP ?, §4.21 RLMP ?)."""

from enum import Enum

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender

_UNPARSABLE_STATUS = "unparsable lamp status"


class Lamp:
    """Status information about the projector light sources (§4.8).

    According to the spec the "usage time of lamp is always 0 when it is
    not counted by the projector." A projector without a lamp (a display, say) raises
    `PJLinkNotSupportedError("no lamp")`.
    """

    class State(Enum):
        """Whether a lamp is lit (§4.8)."""

        OFF = "0"
        ON = "1"

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the lamp status command handler."""
        self._sender = sender

    async def status(self) -> list[tuple[int, State]]:
        """Query lamp usage and status (§4.8).

        Returns:
            One ``(hours, state)`` pair per lamp.

        Raises:
            PJLinkUnexpectedValueError: The lamp status response is malformed.
        """
        response_parameter = await self._sender.query_status("LAMP", PJClass.ONE, not_supported_message="no lamp")
        tokens = response_parameter.split()
        if not tokens:
            raise PJLinkUnexpectedValueError(_UNPARSABLE_STATUS)
        try:
            # The answer alternates usage time and state: `<hours> <0|1> [<hours> <0|1> ...]`.
            hours_and_states = zip(tokens[::2], tokens[1::2], strict=True)
            return [(int(hours), Lamp.State(state)) for hours, state in hours_and_states]
        except ValueError as err:
            raise PJLinkUnexpectedValueError(_UNPARSABLE_STATUS) from err

    async def hours(self) -> int:
        """Query the usage time of the first lamp (§4.8).

        Returns:
            Usage time in hours (0 if the projector does not count it).

        Raises:
            PJLinkUnexpectedValueError: The lamp status response is malformed.
        """
        return (await self.status())[0][0]

    async def replacement_models(self) -> list[str]:
        """Get the lamp replacement models listed in the projector (§4.21).

        Returns:
            The lamp replacement model numbers.
        """
        models = await self._sender.transmit("RLMP", "?", PJClass.TWO)
        return [model for model in models.split(" ") if model]
