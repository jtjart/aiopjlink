"""commands/freeze.py

Freeze the picture (§4.25 FREZ, §4.26 FREZ ?).
"""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup


class Freeze(CommandGroup):
    """Controls freezing and unfreezing the current frame (§4.25, §4.26)."""

    async def set(self, freeze: bool) -> None:
        """Freeze or unfreeze the screen (§4.25)."""
        cmd = "1" if bool(freeze) else "0"
        await self._transmit_ok("FREZ", cmd, pjclass=PJClass.TWO)

    async def get(self) -> bool:
        """Returns True if the screen is currently frozen, and False if not §4.26."""
        response = await self._link.transmit("FREZ", "?", pjclass=PJClass.TWO)
        if response == "0":
            return False
        if response == "1":
            return True
        raise PJLinkUnexpectedResponseParameter("unexpected freeze state")
