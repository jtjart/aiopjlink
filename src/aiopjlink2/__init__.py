"""aiopjlink2: asyncio control of PJLink-compatible projectors over TCP/IP.

Create one `PJLink` and use its command groups (`power`, `sources`, `mute`, `errors`,
`lamps`, `filter`, `freeze`, `speaker`, `microphone`, `info`)::

    async with PJLink(address="192.168.1.120", password="secret") as link:
        await link.power.turn_on()
        print(await link.errors.query())

Projectors on the network are found with `search`, which yields each one as it answers::

    async for found in search(duration_seconds=12):
        print(found.address, found.mac_address)

A projector that has been set up to do so reports changes of its state by itself (power, errors, input).
`listen_notifications` yields them as they arrive, from all the projectors of the network::

    async for notification in listen_notifications():
        print(notification.address, notification.event)

Everything raised while talking to a projector derives from `PJLinkError`.
See the README for connection handling and error handling.
"""

from __future__ import annotations

from ._notify import (
    ErrorsChanged,
    InputChanged,
    LinkUp,
    Notification,
    NotificationEvent,
    PowerChanged,
    listen_notifications,
)
from ._search import SearchResult, search
from ._version import __version__
from .client import PJLink
from .commands import Errors, Filter, Freeze, Information, Lamp, Mute, Power, Sources, Volume
from .enums import PJAuth, PJClass
from .exceptions import (
    PJLinkAuthenticationError,
    PJLinkConnectionClosedError,
    PJLinkConnectionError,
    PJLinkError,
    PJLinkInvalidParameterError,
    PJLinkMalfunctionError,
    PJLinkNoConnectionError,
    PJLinkNotReadyError,
    PJLinkNotSupportedError,
    PJLinkProjectorError,
    PJLinkProtocolError,
    PJLinkUnexpectedValueError,
)

__all__ = [
    "Errors",
    "ErrorsChanged",
    "Filter",
    "Freeze",
    "Information",
    "InputChanged",
    "Lamp",
    "LinkUp",
    "Mute",
    "Notification",
    "NotificationEvent",
    "PJAuth",
    "PJClass",
    "PJLink",
    "PJLinkAuthenticationError",
    "PJLinkConnectionClosedError",
    "PJLinkConnectionError",
    "PJLinkError",
    "PJLinkInvalidParameterError",
    "PJLinkMalfunctionError",
    "PJLinkNoConnectionError",
    "PJLinkNotReadyError",
    "PJLinkNotSupportedError",
    "PJLinkProjectorError",
    "PJLinkProtocolError",
    "PJLinkUnexpectedValueError",
    "Power",
    "PowerChanged",
    "SearchResult",
    "Sources",
    "Volume",
    "__version__",
    "listen_notifications",
    "search",
]
