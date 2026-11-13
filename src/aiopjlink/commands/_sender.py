"""commands/_sender.py

Sending one command to the projector and reading its answer the way the command groups need it.
"""

from .._protocol import PJCommand
from .._transport import Transport
from ..enums import PJClass
from ..exceptions import PJLinkNotReady, PJLinkNotSupported, PJLinkUnexpectedResponseParameter


class CommandSender:
    """What every command group uses to talk to the projector.

    A group is given one instead of inheriting these methods, so it only contains what is particular to its
    own commands. The sender adds to `Transport.transmit` what the spec says about the meaning of answers
    (`ERR1` for "no lamp", `OK` where a value was asked for, ...).
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def transmit(
        self, command: str, parameter: str, pjclass: PJClass, *, not_supported_message: str | None = None
    ) -> str:
        """Transmit a command and return the response parameter.

        The spec gives `ERR1` a specific meaning for some commands ("no lamp", "speaker not installed", ...).
        Pass that meaning as `not_supported_message` and a `PJLinkNotSupported` raised for this command carries it
        as its message.
        """
        try:
            return await self._transport.transmit(PJCommand(command, parameter, pjclass))
        except PJLinkNotSupported as err:
            if not_supported_message is not None and err.command is not None:
                raise PJLinkNotSupported(not_supported_message, command=command) from err
            raise

    async def query_status(self, command: str, pjclass: PJClass, *, not_supported_message: str | None = None) -> str:
        """Query a status value (numbers, flags, lists - never free text) and return the response parameter.

        Some projectors answer `OK` instead of a value while they are not ready (just after a state
        change, or in standby). `OK` is not a valid answer to a query, so it is reported as `PJLinkNotReady`
        ("unavailable in the current state"), exactly as if the projector had said so.

        Do not use this for queries that return free text (names, serial numbers, ...): `OK` is a valid value there.
        See `transmit` for `not_supported_message`.
        """
        response_parameter = await self.transmit(command, "?", pjclass, not_supported_message=not_supported_message)
        if response_parameter.upper() == "OK":
            raise PJLinkNotReady("projector answered a status query with OK", command=command)
        return response_parameter

    async def transmit_expecting_ok(
        self, command: str, parameter: str, pjclass: PJClass, *, not_supported_message: str | None = None
    ) -> None:
        """Transmit a command and check the response is OK.

        See `transmit` for `not_supported_message`.
        """
        response_parameter = await self.transmit(
            command, parameter, pjclass, not_supported_message=not_supported_message
        )
        if response_parameter.upper() != "OK":
            raise PJLinkUnexpectedResponseParameter("expected OK response")
