"""commands/base.py

Base class for the groups of related PJLink commands.
"""

from .._transport import Transport
from ..enums import PJClass
from ..exceptions import PJLinkNotReady, PJLinkNotSupported, PJLinkUnexpectedResponseParameter


class CommandGroup:
    """Base class for related groups of PJLink functionality."""

    def __init__(self, link: Transport) -> None:
        self._link = link

    async def _transmit_value(self, command: str, param: str, pjclass: PJClass, *, err1: str | None = None) -> str:
        """Transmit a command and return the response parameter.

        The spec gives `ERR1` a specific meaning for some commands ("no lamp", "speaker not installed", ...).
        Pass that meaning as `err1` and a `PJLinkNotSupported` raised for this command carries it as its message.
        """
        try:
            return await self._link.transmit(command, param, pjclass)
        except PJLinkNotSupported as err:
            if err1 is None:
                raise
            raise PJLinkNotSupported(err1, command=command) from err

    async def _transmit_state(self, command: str, pjclass: PJClass, *, err1: str | None = None) -> str:
        """Query a status value (numbers, flags, lists - never free text) and return the response parameter.

        Some projectors answer `OK` instead of a value while they are not ready (just after a state
        change, or in standby). `OK` is not a valid answer to a query, so it is reported as `PJLinkNotReady`
        ("unavailable in the current state"), exactly as if the projector had said so.

        Do not use this for queries that return free text (names, serial numbers, ...): `OK` is a valid value there.
        See `_transmit_value` for `err1`.
        """
        response = await self._transmit_value(command, "?", pjclass, err1=err1)
        if response.upper() == "OK":
            raise PJLinkNotReady("projector answered a status query with OK", command=command)
        return response

    async def _transmit_ok(self, command: str, param: str, pjclass: PJClass, *, err1: str | None = None) -> None:
        """Transmit a command and check the response is OK. See `_transmit_value` for `err1`."""
        response = await self._transmit_value(command, param, pjclass, err1=err1)
        if response.upper() != "OK":
            raise PJLinkUnexpectedResponseParameter("expected OK response")
