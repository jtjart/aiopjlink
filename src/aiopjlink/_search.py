"""_search.py

Searching the network for projectors (§3.2 SRCH, ACKN).

The search protocol is connectionless: the controller broadcasts one UDP datagram (`%2SRCH`) to port 4352 and
every projector that hears it answers, after a random delay of 0 to 10 seconds, with a datagram that holds its
MAC address (`%2ACKN=xx:xx:xx:xx:xx:xx`). The controller listens for 30 seconds (§3.2.1) and then connects to
the projectors it found, by the address the answer came from. No authentication is involved (§6), and since it
is UDP either datagram can get lost, so a projector that does not show up is not necessarily absent.

Nothing here uses `Transport`: there is no connection, no password and no per-command answer, so the search
has a socket of its own. Everything a stranger on the network might send to port 4352 is ignored, not raised.
"""

import asyncio
import dataclasses
import socket
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from ._debug import LOGGER
from ._protocol import SEARCH_REQUEST, parse_search_response
from .exceptions import PJLinkNoConnection, PJLinkProtocolError

PJLINK_PORT = 4352
"""The UDP port a projector listens on for the search (§3.2)."""

DEFAULT_SEARCH_DURATION = 30.0
"""How long the controller listens for answers (§3.2.1, step 2), in seconds."""

DEFAULT_BROADCAST_ADDRESS = "255.255.255.255"
"""The IPv4 limited broadcast address: it goes out of the interface the operating system picks."""


@dataclasses.dataclass(frozen=True, slots=True)
class SearchResult:
    """A projector that answered a search (§3.2.2)."""

    address: str
    """The IP address the answer came from. It can be used as it is for `PJLink(address=...)`."""

    mac_address: str
    """The MAC address the projector reported, in lower case: `aa:bb:cc:dd:ee:ff`."""


def _source_address(addr: tuple[Any, ...]) -> str:
    """The IP address a datagram came from, as a string that can be connected to.

    An IPv6 link-local address is only meaningful together with the interface it was seen on. The operating
    system reports that as a separate scope id (and some also write it after a `%` in the address), so it is
    added here when it is missing: `fe80::1%3`.
    """
    host = str(addr[0])
    if len(addr) >= 4 and addr[3] and "%" not in host:
        return f"{host}%{addr[3]}"
    return host


class _SearchProtocol(asyncio.DatagramProtocol):
    """Collects the search responses that arrive on the socket."""

    def __init__(self, results: asyncio.Queue[SearchResult]) -> None:
        self._results = results
        self._seen: set[SearchResult] = set()

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        source = _source_address(addr)
        try:
            mac_address = parse_search_response(data.decode("ascii", errors="replace"))
        except PJLinkProtocolError as err:
            # Includes our own request when the network loops a broadcast back to us.
            LOGGER.debug("ignoring datagram from %s: %s", source, err)
            return

        result = SearchResult(source, mac_address)
        if result in self._seen:
            LOGGER.debug("ignoring repeated search response from %s", source)
            return
        self._seen.add(result)
        LOGGER.debug("search response from %s: %s", source, mac_address)
        self._results.put_nowait(result)

    def error_received(self, exc: Exception) -> None:
        # The operating system reporting an earlier datagram as undeliverable (ICMP). Nothing to do about it.
        LOGGER.debug("search datagram error: %s", exc)


def _resolve(host: str, port: int, what: str) -> tuple[socket.AddressFamily, tuple[Any, ...]]:
    """Turn an IP address literal (not a host name: nothing here may block on DNS) into `(family, sockaddr)`.

    The `sockaddr` is what the `socket` methods take. For IPv6 it carries the scope id of `ff02::1%eth0`,
    which a plain `(host, port)` tuple would lose.
    """
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM, 0, socket.AI_NUMERICHOST)
    except (socket.gaierror, UnicodeError) as err:
        raise ValueError(f"{what} is not a usable IP address: {host!r}") from err
    family, _, _, _, sockaddr = infos[0]
    return family, sockaddr


def _resolve_targets(
    broadcast_address: str | Sequence[str], port: int
) -> tuple[socket.AddressFamily, list[tuple[Any, ...]]]:
    """The `sockaddr` to send the search to for each address given, and their (common) address family."""
    addresses = [broadcast_address] if isinstance(broadcast_address, str) else list(broadcast_address)
    if not addresses:
        raise ValueError("at least one broadcast address is required")
    resolved = [_resolve(address, port, "broadcast_address") for address in addresses]
    families = {family for family, _ in resolved}
    if len(families) != 1:
        raise ValueError("broadcast_address must not mix IPv4 and IPv6 addresses")
    return families.pop(), list(dict.fromkeys(sockaddr for _, sockaddr in resolved))


def _resolve_local(local_address: str | None, local_port: int, family: socket.AddressFamily) -> tuple[Any, ...]:
    """The `sockaddr` to bind to: the wildcard address of `family`, or `local_address`, which must be of that family."""
    if local_address is None:
        return ("0.0.0.0" if family == socket.AF_INET else "::", local_port)
    local_family, sockaddr = _resolve(local_address, local_port, "local_address")
    if local_family != family:
        raise ValueError("local_address must be of the same IP version as broadcast_address")
    return sockaddr


def _open_socket(family: socket.AddressFamily, local: tuple[Any, ...]) -> socket.socket:
    """Create the non-blocking UDP socket the search sends from and listens on."""
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
    except OSError as err:
        raise PJLinkNoConnection(f"search failed - {err}") from err
    try:
        sock.setblocking(False)
        if family == socket.AF_INET:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(local)
    except OSError as err:
        sock.close()
        raise PJLinkNoConnection(f"search failed - {err}") from err
    return sock


def _send_requests(sock: socket.socket, targets: list[tuple[Any, ...]]) -> None:
    """Send the search start instruction to every target. Fails only if none of them could be sent to.

    The datagram is sent on the socket itself rather than through the asyncio transport, because the transport
    reports a failed send to the protocol later, where the caller of the search can no longer see it.
    """
    errors: list[OSError] = []
    for target in targets:
        LOGGER.debug("sending search request to %s", target[0])
        try:
            sock.sendto(SEARCH_REQUEST, target)
        except OSError as err:
            LOGGER.debug("could not send search request to %s: %s", target[0], err)
            errors.append(err)
    if len(errors) == len(targets):
        raise PJLinkNoConnection(f"search failed - {errors[0]}") from errors[0]


async def search_iter(
    *,
    duration: float = DEFAULT_SEARCH_DURATION,
    broadcast_address: str | Sequence[str] = DEFAULT_BROADCAST_ADDRESS,
    port: int = PJLINK_PORT,
    local_address: str | None = None,
    local_port: int = PJLINK_PORT,
) -> AsyncGenerator[SearchResult, None]:
    """Search for projectors and yield each one as soon as it answers (§3.2).

    Sends the search start instruction, then listens for `duration` seconds. A projector that answers more than
    once is yielded once. Datagrams that are not search responses are ignored.

    To stop early, leave the loop and close the generator, so the socket is released at once::

        async with contextlib.aclosing(search_iter()) as results:
            async for result in results:
                if result.mac_address == wanted:
                    break

    Args:
        duration: How long to listen, in seconds. The spec says 30. Projectors answer after a random delay of
            up to 10 seconds, so a shorter time than about 11 may miss some of them.
        broadcast_address: Where to send the search: the broadcast address of the network
            (e.g. `192.168.0.255`, which is `255.255.255.255` on the network 192.168.0.0/24), `ff02::1` for IPv6
            (give the interface as `ff02::1%eth0` when the machine has several), or a list of them to search
            several networks at once (all IPv4 or all IPv6). The default, `255.255.255.255`, only reaches the
            network the operating system chooses, so name the networks on a machine that has more than one.
            The address of a single projector works as well. Host names are not accepted.
        port: The UDP port the projectors listen on. This is 4352 (§3.2).
        local_address: The address of the local interface to send from and listen on. Default: all of them.
        local_port: The local UDP port to send from and listen on. The projector may answer the port the
            request came from or port 4352 (Fig. 1 of the spec leaves that open), and 4352 is right for both,
            so that is the default. It means that only one search can run per local address at a time:
            a second one fails with `PJLinkNoConnection`. 0 lets the operating system choose a port,
            which only suits projectors that answer the port the request came from.

    Yields:
        `SearchResult`, in the order the projectors answered.

    Raises:
        ValueError: An argument is not valid (raised when the iteration starts, before anything is sent).
        PJLinkNoConnection: The socket could not be opened or bound (e.g. the local port is in use), or the
            search start instruction could not be sent at all (e.g. there is no network).
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    if not 0 < port < 65536:
        raise ValueError("port must be between 1 and 65535")
    if not 0 <= local_port < 65536:
        raise ValueError("local_port must be between 0 and 65535")
    family, targets = _resolve_targets(broadcast_address, port)
    local = _resolve_local(local_address, local_port, family)

    loop = asyncio.get_running_loop()
    results: asyncio.Queue[SearchResult] = asyncio.Queue()
    sock = _open_socket(family, local)
    try:
        transport, _ = await loop.create_datagram_endpoint(lambda: _SearchProtocol(results), sock=sock)
    except BaseException:
        sock.close()
        raise

    try:
        _send_requests(sock, targets)
        deadline = loop.time() + duration
        while True:
            try:
                result = results.get_nowait()
            except asyncio.QueueEmpty:
                try:
                    # The timeout only covers the wait, never a `yield`: it would otherwise cancel the caller.
                    async with asyncio.timeout_at(deadline):
                        result = await results.get()
                except TimeoutError:
                    return
            yield result
    finally:
        # The transport gives the socket back on the next iteration of the event loop. Let that happen, so that
        # whoever searches next (on the same local port) does not find it still in use.
        transport.close()
        await asyncio.sleep(0)


async def search(
    *,
    duration: float = DEFAULT_SEARCH_DURATION,
    broadcast_address: str | Sequence[str] = DEFAULT_BROADCAST_ADDRESS,
    port: int = PJLINK_PORT,
    local_address: str | None = None,
    local_port: int = PJLINK_PORT,
) -> list[SearchResult]:
    """Search for projectors, wait `duration` seconds and return all that answered (§3.2).

    This is `search_iter` collected into a list; see there for the arguments and the exceptions.
    Use `search_iter` instead to react to a projector as soon as it answers.
    """
    return [
        result
        async for result in search_iter(
            duration=duration,
            broadcast_address=broadcast_address,
            port=port,
            local_address=local_address,
            local_port=local_port,
        )
    ]
