"""_notify.py

Status notifications sent by projectors on their own (§3.3 LKUP, ERST, POWR, INPT).

A projector that has been told the controller's address (how is not part of the specification: it is a setting
of the projector) sends a UDP datagram to port 4352 of the controller whenever its state changes: it starts
warming up or cooling down, an error appears or goes away, an input switch is completed, or its PJLink
communication becomes ready (§3.3). The controller only listens; it sends nothing and nobody answers.

Like the search, this protocol is connectionless and has no authentication (§6): a notification can get lost, and
anyone on the network can send one. A notification says that something changed, not that it can be trusted, so
a controller that acts on it should ask the projector (over the authenticated TCP connection) what the state is.

Nothing here uses `Transport`. There is no connection and no password, so the listener has a socket of its own,
opened like the search's (see `aiopjlink._udp`). Everything a stranger on the network might send to port 4352,
including the search protocol's own datagrams, is ignored, not raised.
"""

import asyncio
import dataclasses
import socket
from collections.abc import AsyncGenerator
from typing import Any

from ._debug import LOGGER
from ._protocol import parse_mac_address, split_notification
from ._udp import MAX_PORT_NUMBER, PJLINK_UDP_PORT, open_socket, resolve_address, source_address
from .commands.errors import Errors, parse_error_levels
from .commands.sources import Sources, parse_input_source
from .exceptions import PJLinkNoConnection, PJLinkProtocolError, PJLinkUnexpectedResponseParameter

# The notifications that have arrived but are not yet taken by the caller. The port is open to the whole network and
# nothing authenticates the sender, so a slow caller must not let a flood of datagrams use up memory. UDP loses
# datagrams anyway: when the queue is full the newest notification is dropped.
_MAX_PENDING_NOTIFICATIONS = 256


@dataclasses.dataclass(frozen=True, slots=True)
class LinkUp:
    """The projector's PJLink communication is ready, e.g. because its power cable was connected (`LKUP`, §3.3)."""

    mac_address: str
    """The MAC address the projector reported, in lower case: `aa:bb:cc:dd:ee:ff`. It stays the same when the
    projector's IP address changes, so it can be matched with `SearchResult.mac_address`."""


@dataclasses.dataclass(frozen=True, slots=True)
class ErrorsChanged:
    """The error status of the projector changed (`ERST`, §3.3.2). Same form as `Errors.query()`."""

    levels: dict[Errors.Category, Errors.Level]


@dataclasses.dataclass(frozen=True, slots=True)
class PowerChanged:
    """The projector started to warm up or cool down, or switched on or off if it does neither (`POWR`, §3.3.2).

    The notification only has two values, so it cannot tell the transitional states from the stable ones:
    ask `Power.get()` for the exact `Power.State` if that matters.
    """

    powered_on: bool
    """True: power on (lamp on) or warming up. False: power off (standby) or cooling down."""


@dataclasses.dataclass(frozen=True, slots=True)
class InputChanged:
    """An input switch is completed, to the input in `mode` and `index` (`INPT`, §3.3.2).

    The same form as `Sources.get()` returns.
    """

    mode: Sources.Mode
    index: str
    """A single character: 1-9 for Class 1, 1-9 and A-Z for Class 2."""


NotificationEvent = LinkUp | ErrorsChanged | PowerChanged | InputChanged
"""What a projector can notify (§3.3.2). Tell them apart with `isinstance` or a `match` statement."""


@dataclasses.dataclass(frozen=True, slots=True)
class Notification:
    """A status notification and the projector it came from."""

    address: str
    """The IP address the notification came from. It is what `PJLink(address=...)` was given, so the
    notification of one projector can be told from that of another."""

    event: NotificationEvent


def parse_event(datagram_text: str) -> NotificationEvent:
    """Turn the text of a notification datagram (§3.3.2) into the event it describes.

    Raises `PJLinkProtocolError` if it is not a notification, and `PJLinkUnexpectedResponseParameter`
    if it is one but holds a value that is not defined for it.
    """
    command, parameter = split_notification(datagram_text)
    if command == "LKUP":
        mac_address = parse_mac_address(parameter)
        if mac_address is None:
            raise PJLinkProtocolError("unexpected MAC address in status notification")
        return LinkUp(mac_address)
    if command == "ERST":
        return ErrorsChanged(parse_error_levels(parameter))
    if command == "POWR":
        if parameter not in ("0", "1"):
            raise PJLinkUnexpectedResponseParameter("unexpected power status notification")
        return PowerChanged(powered_on=parameter == "1")
    if command == "INPT":
        mode, index = parse_input_source(parameter)
        return InputChanged(mode, index)
    raise PJLinkProtocolError(f"unexpected status notification command: {command}")


class _NotificationProtocol(asyncio.DatagramProtocol):
    """Collects the status notifications that arrive on the socket."""

    def __init__(self, notification_queue: asyncio.Queue[Notification]) -> None:
        self._notification_queue = notification_queue

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        sender_address = source_address(addr)
        try:
            event = parse_event(data.decode("ascii", errors="replace"))
        except (PJLinkProtocolError, PJLinkUnexpectedResponseParameter) as err:
            # Includes the search protocol's datagrams, which use the same port.
            LOGGER.debug("ignoring datagram from %s: %s", sender_address, err)
            return

        try:
            self._notification_queue.put_nowait(Notification(sender_address, event))
        except asyncio.QueueFull:
            LOGGER.debug("dropping status notification from %s: too many are waiting to be taken", sender_address)
            return
        LOGGER.debug("status notification from %s: %s", sender_address, event)

    def error_received(self, exc: Exception) -> None:
        # The operating system reporting an earlier datagram as undeliverable (ICMP). Nothing to do about it.
        LOGGER.debug("status notification datagram error: %s", exc)


async def listen_notifications(
    *,
    local_address: str | None = None,
    local_port: int = PJLINK_UDP_PORT,
) -> AsyncGenerator[Notification, None]:
    """Listen for status notifications and yield each one as it arrives (§3.3).

    Listens until the generator is closed or the task that iterates it is cancelled; close it when you are
    done, so the socket is released at once::

        async with contextlib.aclosing(listen_notifications()) as notifications:
            async for notification in notifications:
                ...

    One listener serves all the projectors of the network: `Notification.address` says which one a
    notification is from. Only one listener can run per local address and port.

    The projectors have to be set up to send their notifications to the machine this runs on; that is a setting
    of the projector (§3.3: "the IP address registered in advance"). Notifications can get lost and are not
    authenticated (§6): see the README for how to deal with that.

    Args:
        local_address: The address of the local interface to listen on. Default: all IPv4 interfaces. Give `::`
            (or the address of one interface) to listen for IPv6. A listener is for one IP version.
        local_port: The local UDP port to listen on. The projectors send to 4352 (§3.3) and that is the default;
            change it only if something forwards the datagrams from there. The search (`search`) uses this port
            as well by default, so it cannot run at the same time: see the README.

    Yields:
        `Notification`, in the order they arrived.

    Raises:
        ValueError: An argument is not valid (raised when the iteration starts).
        PJLinkNoConnection: The socket could not be opened or bound, e.g. because the local port is in use.
    """
    if not 0 < local_port < MAX_PORT_NUMBER:
        raise ValueError("local_port must be between 1 and 65535")
    if local_address is None:
        family, local_sockaddr = socket.AF_INET, ("0.0.0.0", local_port)
    else:
        family, local_sockaddr = resolve_address(local_address, local_port, "local_address")

    pending_notifications: asyncio.Queue[Notification] = asyncio.Queue(_MAX_PENDING_NOTIFICATIONS)
    try:
        udp_socket = open_socket(family, local_sockaddr, enable_broadcast=False)
    except OSError as err:
        raise PJLinkNoConnection(f"listening for notifications failed - {err}") from err
    try:
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: _NotificationProtocol(pending_notifications), sock=udp_socket
        )
    except BaseException:
        udp_socket.close()
        raise

    try:
        while True:
            yield await pending_notifications.get()
    finally:
        # The transport gives the socket back on the next iteration of the event loop. Let that happen, so that
        # whoever listens next (on the same local port) does not find it still in use.
        transport.close()
        await asyncio.sleep(0)
