"""commands/base.py

Base class for the groups of related PJLink commands.
"""

from .._transport import Transport
from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter


class CommandGroup:
    """Base class for related groups of PJLink functionality."""

    def __init__(self, link: Transport) -> None:
        self._link = link

    async def _transmit_ok(self, command: str, param: str, pjclass: PJClass) -> None:
        """Transmit a command and check the response is OK."""
        response = await self._link.transmit(command, param, pjclass)
        if response.upper() != "OK":
            raise PJLinkUnexpectedResponseParameter("expected OK response")
