"""_udp.py

Socket plumbing shared by the two UDP protocols: the search (§3.2) and the status notifications (§3.3).

Both use UDP port 4352 on the controller's side as well as on the projector's, so they open their sockets the
same way and report the sender of a datagram the same way. What they do with a datagram is up to them.
"""

import socket
from typing import Any

PJLINK_UDP_PORT = 4352
"""The UDP port of the PJLink search and status notification protocols (§3.2, §3.3)."""


def source_address(datagram_sender: tuple[Any, ...]) -> str:
    """The IP address a datagram came from, as a string that can be connected to.

    An IPv6 link-local address is only meaningful together with the interface it was seen on. The operating
    system reports that as a separate scope id (and some also write it after a `%` in the address), so it is
    added here when it is missing: `fe80::1%3`.
    """
    host = str(datagram_sender[0])
    if len(datagram_sender) >= 4 and datagram_sender[3] and "%" not in host:
        return f"{host}%{datagram_sender[3]}"
    return host


def resolve_address(host: str, port: int, argument_name: str) -> tuple[socket.AddressFamily, tuple[Any, ...]]:
    """Turn an IP address literal (not a host name: nothing here may block on DNS) into `(family, sockaddr)`.

    The `sockaddr` is what the `socket` methods take. For IPv6 it carries the scope id of `ff02::1%eth0`,
    which a plain `(host, port)` tuple would lose. `argument_name` names the argument in the `ValueError`.
    """
    if not host:
        # Not left to `getaddrinfo`: macOS takes an empty string for "no host" and answers with a loopback address.
        raise ValueError(f"{argument_name} is not a usable IP address: {host!r}")
    try:
        address_infos = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM, 0, socket.AI_NUMERICHOST)
    except (socket.gaierror, UnicodeError) as err:
        raise ValueError(f"{argument_name} is not a usable IP address: {host!r}") from err
    family, _, _, _, sockaddr = address_infos[0]
    return family, sockaddr


def open_socket(
    family: socket.AddressFamily, local_sockaddr: tuple[Any, ...], *, enable_broadcast: bool
) -> socket.socket:
    """Create a non-blocking UDP socket bound to `local_sockaddr`.

    Set `enable_broadcast` if it is to send to broadcast addresses.

    Raises `OSError` if the socket cannot be created or bound; the caller says in its own words what failed.
    """
    udp_socket = socket.socket(family, socket.SOCK_DGRAM)
    try:
        udp_socket.setblocking(False)
        if enable_broadcast and family == socket.AF_INET:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.bind(local_sockaddr)
    except OSError:
        udp_socket.close()
        raise
    return udp_socket
