"""Freeze the picture (§4.25 FREZ, §4.26 FREZ ?)."""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedValueError
from ._sender import CommandSender


class Freeze:
    """Controls freezing and unfreezing the current frame (§4.25, §4.26).

    A projector that cannot freeze raises `PJLinkNotSupportedError("freeze not supported")`.
    """

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the freeze command handler."""
        self._sender = sender

    async def set(self, frozen: bool) -> None:
        """Freeze or unfreeze the screen (§4.25)."""
        parameter = "1" if bool(frozen) else "0"
        await self._sender.transmit_expecting_ok(
            "FREZ", parameter, PJClass.TWO, not_supported_message="freeze not supported"
        )

    async def get(self) -> bool:
        """Return True if the screen is currently frozen, and False if not (§4.26)."""
        response_parameter = await self._sender.query_status(
            "FREZ", PJClass.TWO, not_supported_message="freeze not supported"
        )
        if response_parameter == "0":
            return False
        if response_parameter == "1":
            return True
        raise PJLinkUnexpectedValueError("unexpected freeze state")
