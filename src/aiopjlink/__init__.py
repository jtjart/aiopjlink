"""aiopjlink: asyncio control of PJLink-compatible projectors over TCP/IP."""

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
