"""commands/base.py

Base class for the groups of related PJLink commands.
"""

from .._protocol import PJCommand
from .._transport import Transport
from ..enums import PJClass
from ..exceptions import PJLinkNotReady, PJLinkNotSupported, PJLinkUnexpectedResponseParameter


class CommandGroup:
    """Base class for related groups of PJLink functionality."""

    def __init__(self, link: Transport) -> None:
        self._link = link

    async def _transmit_response_parameter(
        self, command: str, parameter: str, pjclass: PJClass, *, not_supported_message: str | None = None
    ) -> str:
        """Transmit a command and return the response parameter.

        The spec gives `ERR1` a specific meaning for some commands ("no lamp", "speaker not installed", ...).
        Pass that meaning as `not_supported_message` and a `PJLinkNotSupported` raised for this command carries it
        as its message.
        """
        try:
            return await self._link.transmit(PJCommand(command, parameter, pjclass))
        except PJLinkNotSupported as err:
            if not_supported_message is None:
                raise
            raise PJLinkNotSupported(not_supported_message, command=command) from err

    async def _query_status(self, command: str, pjclass: PJClass, *, not_supported_message: str | None = None) -> str:
        """Query a status value (numbers, flags, lists - never free text) and return the response parameter.

        Some projectors answer `OK` instead of a value while they are not ready (just after a state
        change, or in standby). `OK` is not a valid answer to a query, so it is reported as `PJLinkNotReady`
        ("unavailable in the current state"), exactly as if the projector had said so.

        Do not use this for queries that return free text (names, serial numbers, ...): `OK` is a valid value there.
        See `_transmit_response_parameter` for `not_supported_message`.
        """
        response_parameter = await self._transmit_response_parameter(
            command, "?", pjclass, not_supported_message=not_supported_message
        )
        if response_parameter.upper() == "OK":
            raise PJLinkNotReady("projector answered a status query with OK", command=command)
        return response_parameter

    async def _transmit_expecting_ok(
        self, command: str, parameter: str, pjclass: PJClass, *, not_supported_message: str | None = None
    ) -> None:
        """Transmit a command and check the response is OK.

        See `_transmit_response_parameter` for `not_supported_message`.
        """
        response_parameter = await self._transmit_response_parameter(
            command, parameter, pjclass, not_supported_message=not_supported_message
        )
        if response_parameter.upper() != "OK":
            raise PJLinkUnexpectedResponseParameter("expected OK response")
