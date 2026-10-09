"""projector.py

Backwards-compatibility shim: everything that used to be defined here now lives in
a module of its own (see `aiopjlink.client`, `aiopjlink.commands`, `aiopjlink.enums`
and `aiopjlink.exceptions`). New code should import from `aiopjlink` directly.
"""

from .client import PJLink
from .commands import CommandGroup, Errors, Filter, Freeze, Information, Lamp, Mute, Power, Sources, Volume
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
]
