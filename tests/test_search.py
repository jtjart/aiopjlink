"""The search protocol (§3.2): one UDP request, any number of answers, no connection.

The mock projector listens on a port chosen by the operating system, and the searches send to it directly
instead of to a broadcast address, so nothing here leaves the machine. They also let the operating system
choose the local port (`local_port=0`) instead of 4352, so tests can run in parallel.
"""

import asyncio
import contextlib
import dataclasses
import errno
import inspect
import socket
import time
import unittest
from unittest import mock

import aiopjlink
from aiopjlink._protocol import SEARCH_REQUEST, parse_search_response
from aiopjlink._search import _SearchProtocol, _source_address

LOCALHOST = "127.0.0.1"
MAC = "00:11:22:33:44:55"
ACKN = b"%2ACKN=00:11:22:33:44:55\r"


class UdpProjector(asyncio.DatagramProtocol):
    """A mock projector: records the datagrams it gets and answers each of them with `replies`."""

    def __init__(self, replies, delay):
        self.replies = replies
        self.delay = delay
        self.requests = []
        self.port = 0
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, addr):
        self.requests.append((data, addr))
        for reply in self.replies:
            asyncio.get_running_loop().call_later(self.delay, self._reply, reply, addr)

    def _reply(self, reply, addr):
        if not self._transport.is_closing():
            self._transport.sendto(reply, addr)


@contextlib.asynccontextmanager
async def udp_projector(*replies, delay=0.0, host=LOCALHOST):
    """A mock projector on a free UDP port. `delay` is how long it waits before it answers."""
    protocol = UdpProjector(replies, delay)
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: protocol, local_addr=(host, 0))
    protocol.port = transport.get_extra_info("sockname")[1]
    try:
        yield protocol
    finally:
        transport.close()


def free_udp_port():
    """A local UDP port nothing is using: asked from the OS and given back at once."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((LOCALHOST, 0))
        return sock.getsockname()[1]


def options(server, **overrides):
    """Arguments that make `search` talk to `server` only, from a port the OS chooses."""
    result = {
        "duration": 0.4,
        "broadcast_address": LOCALHOST,
        "port": server.port,
        "local_address": LOCALHOST,
        "local_port": 0,
    }
    result.update(overrides)
    return result


def ipv6_loopback_available():
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.bind(("::1", 0))
    except OSError:
        return False
    return True


class WireFormatTests(unittest.TestCase):
    """The datagrams are the ones in §3.2.2."""

    def test_request(self):
        """`%2SRCH` and CR: 25 32 53 52 43 48 0d, with no separator and no parameter."""
        self.assertEqual(SEARCH_REQUEST, bytes.fromhex("25 32 53 52 43 48 0d"))

    def test_response(self):
        self.assertEqual(parse_search_response("%2ACKN=00:11:22:33:44:55\r"), MAC)

    def test_response_is_lenient_about_case_and_line_end(self):
        """Postel's law: the MAC address comes out in lower case, and a datagram needs no CR to end it."""
        for data in ("%2ACKN=AA:BB:CC:DD:EE:FF\r", "%2ackn=aa:bb:cc:dd:ee:ff\r", "%2ACKN=aa:bb:cc:dd:ee:ff\r\n"):
            with self.subTest(data=data):
                self.assertEqual(parse_search_response(data), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(parse_search_response("%2ACKN=aa:bb:cc:dd:ee:ff"), "aa:bb:cc:dd:ee:ff")

    def test_not_a_response(self):
        for data in ("", "\r", "garbage", "%2SRCH\r", "%1ACKN=00:11:22:33:44:55\r", "%2ACKN\r"):
            with self.subTest(data=data):
                line = data.rstrip("\r\n")
                with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                    parse_search_response(data)
                self.assertEqual(str(err.exception), f"unexpected search response: {line}")

    def test_not_a_mac_address(self):
        for mac in (
            "",
            "ERR1",
            "00:11:22:33:44",
            "00:11:22:33:44:55:66",
            "00:11:22:33:44:5G",
            "00-11-22-33-44-55",
            " 00:11:22:33:44:55",
            "001122334455",
        ):
            with self.subTest(mac=mac):
                with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                    parse_search_response(f"%2ACKN={mac}\r")
                self.assertEqual(str(err.exception), "unexpected MAC address in search response")


class SourceAddressTests(unittest.TestCase):
    """The address a datagram came from is something `PJLink(address=...)` can connect to."""

    def test_ipv4(self):
        self.assertEqual(_source_address(("192.168.1.20", 4352)), "192.168.1.20")

    def test_ipv6(self):
        self.assertEqual(_source_address(("2001:db8::1", 4352, 0, 0)), "2001:db8::1")

    def test_ipv6_link_local_gets_its_interface(self):
        """Without the scope id, `fe80::1` does not say which network it is on."""
        self.assertEqual(_source_address(("fe80::1", 4352, 0, 3)), "fe80::1%3")

    def test_scope_is_not_added_twice(self):
        self.assertEqual(_source_address(("fe80::1%eth0", 4352, 0, 3)), "fe80::1%eth0")


class ResultTests(unittest.TestCase):
    def test_result_is_a_value(self):
        """Results compare and hash by content, so searches of several networks can be merged in a set."""
        self.assertEqual(aiopjlink.SearchResult("1.2.3.4", MAC), aiopjlink.SearchResult("1.2.3.4", MAC))
        self.assertEqual(len({aiopjlink.SearchResult("1.2.3.4", MAC), aiopjlink.SearchResult("1.2.3.4", MAC)}), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            aiopjlink.SearchResult("1.2.3.4", MAC).address = "5.6.7.8"  # type: ignore[misc]

    def test_public_api(self):
        for name in ("search", "search_iter", "SearchResult"):
            self.assertIn(name, aiopjlink.__all__)

    def test_defaults_follow_the_spec(self):
        """UDP port 4352 on both sides (Fig. 1) and 30 seconds of listening (§3.2.1)."""
        defaults = {name: p.default for name, p in inspect.signature(aiopjlink.search).parameters.items()}
        self.assertEqual(defaults["port"], 4352)
        self.assertEqual(defaults["local_port"], 4352)
        self.assertEqual(defaults["duration"], 30.0)
        self.assertEqual(defaults["broadcast_address"], "255.255.255.255")


class SearchTests(unittest.IsolatedAsyncioTestCase):
    """A search finds the projectors that answer, and only those."""

    async def test_finds_a_projector(self):
        async with udp_projector(ACKN) as server:
            # No local address: listens on every interface, as the default does.
            results = await aiopjlink.search(**options(server, local_address=None))
        self.assertEqual(results, [aiopjlink.SearchResult(LOCALHOST, MAC)])
        self.assertEqual([data for data, _ in server.requests], [SEARCH_REQUEST])

    async def test_mac_address_is_lower_case(self):
        async with udp_projector(b"%2ACKN=AA:BB:CC:DD:EE:FF\r") as server:
            results = await aiopjlink.search(**options(server))
        self.assertEqual(results[0].mac_address, "aa:bb:cc:dd:ee:ff")

    async def test_several_answers_in_the_order_they_came(self):
        async with udp_projector(ACKN, b"%2ACKN=AA:BB:CC:DD:EE:FF\r") as server:
            results = await aiopjlink.search(**options(server))
        self.assertEqual([r.mac_address for r in results], [MAC, "aa:bb:cc:dd:ee:ff"])

    async def test_repeated_answer_is_reported_once(self):
        async with udp_projector(ACKN, ACKN, b"%2ACKN=00:11:22:33:44:55\r") as server:
            results = await aiopjlink.search(**options(server))
        self.assertEqual(len(results), 1)

    async def test_other_datagrams_are_ignored(self):
        """Anyone on the network can send to port 4352: that is no reason to fail."""
        junk = (b"", b"garbage", b"\xff\xfe\xfd\r", b"%2SRCH\r", b"%1ACKN=" + MAC.encode() + b"\r", b"%2ACKN=zz\r")
        async with udp_projector(*junk, ACKN) as server:
            # An exception in the protocol would not fail the search: asyncio logs it and carries on.
            with self.assertNoLogs("asyncio", level="ERROR"):
                results = await aiopjlink.search(**options(server))
        self.assertEqual(results, [aiopjlink.SearchResult(LOCALHOST, MAC)])

    async def test_nobody_answers(self):
        """The search ends after `duration`, with nothing found."""
        async with udp_projector() as server:
            start = time.monotonic()
            results = await aiopjlink.search(**options(server, duration=0.3))
            elapsed = time.monotonic() - start
        self.assertEqual(results, [])
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 1.5)

    async def test_listens_for_the_whole_duration(self):
        """Projectors answer after a random delay (§3.2.1): an answer in the last moments still counts."""
        async with udp_projector(ACKN, delay=0.5) as server:
            start = time.monotonic()
            results = await aiopjlink.search(**options(server, duration=0.9))
            elapsed = time.monotonic() - start
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(elapsed, 0.8)

    async def test_answer_after_the_duration_is_not_waited_for(self):
        async with udp_projector(ACKN, delay=1.5) as server:
            start = time.monotonic()
            results = await aiopjlink.search(**options(server, duration=0.3))
            elapsed = time.monotonic() - start
        self.assertEqual(results, [])
        self.assertLess(elapsed, 1.2)

    async def test_local_port(self):
        """The request is sent from `local_port`, where the answer may be expected (Fig. 1)."""
        port = free_udp_port()
        async with udp_projector(ACKN) as server:
            await aiopjlink.search(**options(server, local_port=port))
        self.assertEqual(server.requests[0][1], (LOCALHOST, port))

    async def test_several_broadcast_addresses(self):
        """The request goes to every address, once each."""
        async with udp_projector(ACKN) as server:
            await aiopjlink.search(**options(server, broadcast_address=[LOCALHOST, "127.0.0.1"]))
        self.assertEqual(len(server.requests), 1)

    @unittest.skipUnless(ipv6_loopback_available(), "no IPv6 loopback")
    async def test_ipv6(self):
        async with udp_projector(ACKN, host="::1") as server:
            results = await aiopjlink.search(**options(server, broadcast_address="::1", local_address="::1"))
        self.assertEqual(results, [aiopjlink.SearchResult("::1", MAC)])


class IterTests(unittest.IsolatedAsyncioTestCase):
    """`search_iter` hands over each projector as soon as it answers, and can be stopped."""

    async def test_yields_before_the_duration_is_over(self):
        async with udp_projector(ACKN) as server:
            start = time.monotonic()
            async with contextlib.aclosing(aiopjlink.search_iter(**options(server, duration=5))) as found:
                first = await anext(found)
            elapsed = time.monotonic() - start
        self.assertEqual(first, aiopjlink.SearchResult(LOCALHOST, MAC))
        self.assertLess(elapsed, 2)

    async def test_slow_consumer_is_left_alone_and_loses_nothing(self):
        """The time limit is not a timer running against the caller, and answers that came in time are kept.

        Both answers arrive at once, the consumer needs longer than the whole `duration` for each of them.
        """
        async with udp_projector(ACKN, b"%2ACKN=AA:BB:CC:DD:EE:FF\r") as server:
            found = []
            async for result in aiopjlink.search_iter(**options(server, duration=0.3)):
                await asyncio.sleep(0.5)
                found.append(result.mac_address)
        self.assertEqual(found, [MAC, "aa:bb:cc:dd:ee:ff"])

    async def test_stopping_early_releases_the_port_at_once(self):
        """The next search, on the same local port, must not find it still in use."""
        port = free_udp_port()
        async with udp_projector(ACKN) as server:
            async with contextlib.aclosing(
                aiopjlink.search_iter(**options(server, duration=5, local_port=port))
            ) as found:
                async for _ in found:
                    break
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind((LOCALHOST, port))

    async def test_cancelling_releases_the_port_at_once(self):
        port = free_udp_port()
        async with udp_projector() as server:
            task = asyncio.create_task(aiopjlink.search(**options(server, duration=5, local_port=port)))
            await asyncio.sleep(0.1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind((LOCALHOST, port))

    async def test_searches_in_a_row_on_the_same_port(self):
        """Back to back, as when a Home Assistant config flow searches again: the port is free every time."""
        port = free_udp_port()
        async with udp_projector(ACKN) as server:
            for _ in range(3):
                results = await aiopjlink.search(**options(server, duration=0.2, local_port=port))
                self.assertEqual(len(results), 1)

    async def test_nothing_happens_before_the_first_iteration(self):
        async with udp_projector(ACKN) as server:
            aiopjlink.search_iter(**options(server))
            await asyncio.sleep(0.1)
        self.assertEqual(server.requests, [])


class SearchErrorTests(unittest.IsolatedAsyncioTestCase):
    """What goes wrong on this machine is a `PJLinkNoConnection`; a wrong argument is a `ValueError`."""

    async def test_local_port_in_use(self):
        """Two searches cannot share a local port: the second one says so."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
            blocker.bind((LOCALHOST, 0))
            port = blocker.getsockname()[1]
            async with udp_projector() as server:
                with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                    await aiopjlink.search(**options(server, local_port=port))
        self.assertTrue(str(err.exception).startswith("search failed - "), str(err.exception))
        self.assertIsInstance(err.exception, aiopjlink.PJLinkConnectionError)

    async def test_local_address_not_on_this_machine(self):
        async with udp_projector() as server:
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await aiopjlink.search(**options(server, local_address="192.0.2.1"))

    async def test_nothing_can_be_sent(self):
        """No network: reported at once, not after `duration`."""
        unreachable = OSError(errno.ENETUNREACH, "Network is unreachable")
        async with udp_projector() as server:
            with mock.patch.object(socket.socket, "sendto", side_effect=unreachable):
                start = time.monotonic()
                with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                    await aiopjlink.search(**options(server, duration=5))
        self.assertLess(time.monotonic() - start, 1)
        self.assertIn("Network is unreachable", str(err.exception))

    async def test_one_address_that_cannot_be_sent_to(self):
        """One network being down does not stop the search of the others."""
        unreachable = "198.51.100.255"
        real_sendto = socket.socket.sendto

        def flaky_sendto(sock, data, addr):
            if addr[0] == unreachable:
                raise OSError(errno.ENETUNREACH, "Network is unreachable")
            return real_sendto(sock, data, addr)

        async with udp_projector(ACKN) as server:
            with mock.patch.object(socket.socket, "sendto", flaky_sendto):
                results = await aiopjlink.search(**options(server, broadcast_address=[unreachable, LOCALHOST]))
        self.assertEqual(len(results), 1)

    async def test_no_socket_can_be_made(self):
        """E.g. a machine without IPv6: the search cannot start, and says so like any other failure of the network."""
        async with udp_projector() as server:
            with mock.patch.object(socket, "socket", side_effect=OSError(errno.EAFNOSUPPORT, "not supported")):
                with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                    await aiopjlink.search(**options(server))
        self.assertEqual(str(err.exception), f"search failed - [Errno {errno.EAFNOSUPPORT}] not supported")

    async def test_socket_is_not_leaked_when_the_loop_cannot_take_it(self):
        """The port was bound already: whatever goes wrong next, it is given back."""
        port = free_udp_port()
        async with udp_projector() as server:
            with mock.patch.object(asyncio.BaseEventLoop, "create_datagram_endpoint", side_effect=RuntimeError("x")):
                with self.assertRaises(RuntimeError):
                    await aiopjlink.search(**options(server, local_port=port))
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind((LOCALHOST, port))

    async def test_undeliverable_datagram_is_no_error(self):
        """The operating system may report an earlier datagram as undeliverable (ICMP). It is no reason to stop."""
        queue = asyncio.Queue()
        _SearchProtocol(queue).error_received(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        self.assertTrue(queue.empty())

    async def test_invalid_arguments(self):
        """Rejected before anything is sent."""
        cases = {
            "duration is zero": {"duration": 0},
            "duration is negative": {"duration": -1},
            "broadcast address is not an address": {"broadcast_address": "not-an-address"},
            "broadcast address is a host name": {"broadcast_address": "localhost"},
            "broadcast address is empty": {"broadcast_address": ""},
            "no broadcast address": {"broadcast_address": []},
            "IPv4 and IPv6 mixed": {"broadcast_address": [LOCALHOST, "::1"]},
            "port is zero": {"port": 0},
            "port is too large": {"port": 65536},
            "local port is negative": {"local_port": -1},
            "local port is too large": {"local_port": 65536},
            "local address is not an address": {"local_address": "not-an-address"},
            "local address is IPv6 for an IPv4 search": {"local_address": "::1"},
        }
        async with udp_projector(ACKN) as server:
            for name, overrides in cases.items():
                with self.subTest(name):
                    with self.assertRaises(ValueError):
                        await aiopjlink.search(**options(server, **overrides))
        self.assertEqual(server.requests, [])
