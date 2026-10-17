"""aiopjlink: asyncio control of PJLink-compatible projectors over TCP/IP.

Create one `PJLink` and use its command groups (`power`, `sources`, `mute`, `errors`,
`lamps`, `filter`, `freeze`, `speaker`, `microphone`, `info`)::

    async with PJLink(address="192.168.1.120", password="secret") as link:
        await link.power.turn_on()
        print(await link.errors.query())

Everything raised while talking to a projector derives from `PJLinkException`.
See the README for connection handling and error handling.
"""

from __future__ import annotations

from ._version import __version__
from .client import PJLink
from .commands import (
    CommandGroup,
    Errors,
    Filter,
    Freeze,
    Information,
    Lamp,
    Mute,
    Power,
    Sources,
    Volume,
)
from .enums import PJClass
from .exceptions import (
    PJLinkConnectionClosed,
    PJLinkConnectionError,
    PJLinkDeviceFailure,
    PJLinkException,
    PJLinkInvalidParameter,
    PJLinkNoConnection,
    PJLinkNotReady,
    PJLinkNotSupported,
    PJLinkPassword,
    PJLinkProjectorError,
    PJLinkProtocolError,
    PJLinkUnexpectedResponseParameter,
)

__all__ = [
    "CommandGroup",
    "Errors",
    "Filter",
    "Freeze",
    "Information",
    "Lamp",
    "Mute",
    "PJClass",
    "PJLink",
    "PJLinkConnectionClosed",
    "PJLinkConnectionError",
    "PJLinkDeviceFailure",
    "PJLinkException",
    "PJLinkInvalidParameter",
    "PJLinkNoConnection",
    "PJLinkNotReady",
    "PJLinkNotSupported",
    "PJLinkPassword",
    "PJLinkProjectorError",
    "PJLinkProtocolError",
    "PJLinkUnexpectedResponseParameter",
    "Power",
    "Sources",
    "Volume",
    "__version__",
]
