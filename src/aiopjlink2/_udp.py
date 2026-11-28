"""Socket plumbing shared by the two UDP protocols: the search (§3.2) and the status notifications (§3.3).

Both use UDP port 4352 on the controller's side as well as on the projector's, so they open their sockets the
same way and report the sender of a datagram the same way. What they do with a datagram is up to them.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncGenerator
from typing import Any

from .exceptions import PJLinkNoConnectionError

PJLINK_UDP_PORT = 4352
"""The UDP port of the PJLink search and status notification protocols (§3.2, §3.3)."""

MAX_PORT_NUMBER = 65535

IPV6_SCOPE_ID_INDEX = 3
"""Position of the scope id in the `sockaddr` of an IPv6 socket: `(host, port, flowinfo, scope_id)`."""


def source_address(datagram_sender: tuple[Any, ...]) -> str:
    """Get the sender address of a datagram as a string that can be connected to.

    For IPv6 link-local addresses, add the scope id if the operating system reports it separately, e.g.
    `fe80::1%3`.

    Returns:
        The sender IP address, including an IPv6 scope id when needed.
    """
    host = str(datagram_sender[0])
    if len(datagram_sender) > IPV6_SCOPE_ID_INDEX and datagram_sender[IPV6_SCOPE_ID_INDEX] and "%" not in host:
        return f"{host}%{datagram_sender[IPV6_SCOPE_ID_INDEX]}"
    return host


def resolve_address(host: str, port: int, argument_name: str) -> tuple[socket.AddressFamily, tuple[Any, ...]]:
    """Resolve a numeric IP address without performing DNS lookup.

    Args:
        argument_name: Name of the argument being validated.

    Returns:
        The address family and `sockaddr`. Returning a `sockaddr` rather than `(host, port)` preserves an IPv6 scope
        id such as the interface in `ff02::1%eth0`.

    Raises:
        ValueError: `host` is empty or is not a numeric IP address.
    """
    if not host:
        raise ValueError(f"{argument_name} is not a usable IP address: {host!r}")
    try:
        address_infos = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM, 0, socket.AI_NUMERICHOST)
    except (socket.gaierror, UnicodeError) as err:
        raise ValueError(f"{argument_name} is not a usable IP address: {host!r}") from err
    family, _, _, _, sockaddr = address_infos[0]
    return family, sockaddr


@contextlib.asynccontextmanager
async def open_endpoint(
    protocol: asyncio.DatagramProtocol,
    family: socket.AddressFamily,
    local_sockaddr: tuple[Any, ...],
    *,
    enable_broadcast: bool,
    purpose: str,
) -> AsyncGenerator[socket.socket, None]:
    """Open a UDP endpoint and close it when the context exits.

    Creates a non-blocking UDP socket, optionally enables IPv4 broadcast, binds it to the local address,
    and attaches the supplied datagram protocol.

    Args:
        purpose: Operation name included in connection errors.

    Yields:
        The open UDP socket.

    Raises:
        PJLinkNoConnectionError: Socket creation or binding fails.
    """
    try:
        udp_socket = socket.socket(family, socket.SOCK_DGRAM)
    except OSError as err:
        raise PJLinkNoConnectionError(f"{purpose} failed - {err}") from err

    try:
        udp_socket.setblocking(False)
        if enable_broadcast and family == socket.AF_INET:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind(local_sockaddr)

    except OSError as err:
        udp_socket.close()
        raise PJLinkNoConnectionError(f"{purpose} failed - {err}") from err

    try:
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: protocol, sock=udp_socket)
    except BaseException:
        # The transport does not own the socket yet, so closing it is up to us (also when we are cancelled).
        udp_socket.close()
        raise

    try:
        yield udp_socket
    finally:
        # The transport gives the socket back on the next iteration of the event loop. Let that happen, so that
        # whoever binds the same local port next does not find it still in use.
        transport.close()
        await asyncio.sleep(0)
