"""The status notification protocol (§3.3): the projector sends UDP datagrams, the controller only listens.

The listener is given a free local port (`local_port`) instead of 4352, so tests neither collide with a real
PJLink service nor with each other, and can run in parallel. A datagram is sent to it from a plain UDP socket.
"""

import asyncio
import contextlib
import dataclasses
import errno
import socket
import unittest
from collections.abc import AsyncGenerator
from typing import Any
from unittest import mock

import aiopjlink
from aiopjlink import (
    ErrorsChanged,
    InputChanged,
    LinkUp,
    Notification,
    PowerChanged,
    listen_notifications,
)
from aiopjlink._notify import _MAX_PENDING_NOTIFICATIONS, _NotificationProtocol, parse_event
from aiopjlink._protocol import parse_mac_address, split_notification
from mock_projector import unused_udp_port

LOCALHOST = "127.0.0.1"
MAC = "00:11:22:33:44:55"
WAIT = 2.0
"""The most a test waits for a notification that is expected to arrive."""

ALL_OK = dict.fromkeys(aiopjlink.Errors.Category, aiopjlink.Errors.Level.OK)


def ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.bind(("::1", 0))
    except OSError:
        return False
    return True


def send(port: int, data: bytes, *, host: str = LOCALHOST) -> None:
    """Send one datagram to `host`, as a projector would."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.sendto(data, (host, port))


def options(port: int, **overrides: Any) -> dict[str, Any]:
    """Arguments that make the listener listen on `port` of the loopback interface only."""
    result: dict[str, Any] = {"local_address": LOCALHOST, "local_port": port}
    result.update(overrides)
    return result


async def take(notifications: AsyncGenerator[Notification, None], count: int) -> list[Notification]:
    """The next `count` notifications, but never wait for longer than `WAIT` for them."""
    async with asyncio.timeout(WAIT):
        return [await anext(notifications) for _ in range(count)]


async def listen_and_send(port: int, *datagrams: bytes, count: int, **overrides: Any) -> list[Notification]:
    """Listen on `port`, send the datagrams to the address listened on, and return the first `count` notifications."""
    async with contextlib.aclosing(listen_notifications(**options(port, **overrides))) as found:
        pending = asyncio.ensure_future(take(found, count))
        await asyncio.sleep(0)  # The listener binds the port when it starts: nothing is lost from here on.
        for datagram in datagrams:
            send(port, datagram, host=overrides.get("local_address", LOCALHOST) or LOCALHOST)
        return await pending


class WireFormatTests(unittest.TestCase):
    """The datagrams are the ones in §3.3.2."""

    def test_split(self) -> None:
        self.assertEqual(split_notification("%2POWR=1\r"), ("POWR", "1"))
        self.assertEqual(split_notification("%2ERST=000000\r"), ("ERST", "000000"))

    def test_split_is_lenient_about_case_and_line_end(self) -> None:
        """Postel's law, as for the search response: a datagram needs no CR to end it."""
        for data in ("%2powr=1\r", "%2POWR=1", "%2POWR=1\r\n"):
            with self.subTest(data=data):
                self.assertEqual(split_notification(data), ("POWR", "1"))

    def test_split_empty_parameter(self) -> None:
        self.assertEqual(split_notification("%2POWR=\r"), ("POWR", ""))

    def test_not_a_notification(self) -> None:
        # The search start instruction and a Class 1 line are not notifications either.
        for data in ("", "\r", "garbage", "%2SRCH\r", "%1POWR=1\r", "%2POWR 1\r", "%2POW=1\r", "2POWR=1\r"):
            with self.subTest(data=data):
                line = data.rstrip("\r\n")
                with self.assertRaises(aiopjlink.PJLinkProtocolError) as err:
                    split_notification(data)
                self.assertEqual(str(err.exception), f"unexpected status notification: {line}")

    def test_mac_address(self) -> None:
        self.assertEqual(parse_mac_address("AA:BB:CC:DD:EE:FF"), "aa:bb:cc:dd:ee:ff")
        for text in ("", "00:11:22:33:44", "00-11-22-33-44-55", "001122334455", "00:11:22:33:44:5G"):
            with self.subTest(text=text):
                self.assertIsNone(parse_mac_address(text))


class ParseEventTests(unittest.TestCase):
    """Every notification in §3.3.2 becomes an event, and nothing else does."""

    def test_link_up(self) -> None:
        self.assertEqual(parse_event(f"%2LKUP={MAC}\r"), LinkUp(MAC))
        self.assertEqual(parse_event("%2lkup=AA:BB:CC:DD:EE:FF\r"), LinkUp("aa:bb:cc:dd:ee:ff"))

    def test_errors(self) -> None:
        self.assertEqual(parse_event("%2ERST=000000\r"), ErrorsChanged(ALL_OK))
        event = parse_event("%2ERST=101020\r")
        self.assertEqual(
            event,
            ErrorsChanged(
                {
                    aiopjlink.Errors.Category.FAN: aiopjlink.Errors.Level.WARN,
                    aiopjlink.Errors.Category.LAMP: aiopjlink.Errors.Level.OK,
                    aiopjlink.Errors.Category.TEMP: aiopjlink.Errors.Level.WARN,
                    aiopjlink.Errors.Category.COVER: aiopjlink.Errors.Level.OK,
                    aiopjlink.Errors.Category.FILTER: aiopjlink.Errors.Level.ERROR,
                    aiopjlink.Errors.Category.OTHER: aiopjlink.Errors.Level.OK,
                }
            ),
        )

    def test_power(self) -> None:
        self.assertEqual(parse_event("%2POWR=1\r"), PowerChanged(powered_on=True))
        self.assertEqual(parse_event("%2POWR=0\r"), PowerChanged(powered_on=False))

    def test_input(self) -> None:
        self.assertEqual(parse_event("%2INPT=31\r"), InputChanged(aiopjlink.Sources.Mode.DIGITAL, "1"))
        # Class 2 indexes go up to Z (§3.3.2: "11 to 6Z").
        self.assertEqual(parse_event("%2INPT=6Z\r"), InputChanged(aiopjlink.Sources.Mode.INTERNAL, "Z"))

    def test_invalid_protocol(self) -> None:
        """Not what a projector would send: `PJLinkProtocolError`."""
        for data in ("%2LKUP=nonsense\r", "%2LKUP=\r", "%2LKUP=00:11:22:33:44\r", "%2ACKN=" + MAC + "\r", "%2XXXX=1\r"):
            with self.subTest(data=data), self.assertRaises(aiopjlink.PJLinkProtocolError):
                parse_event(data)

    def test_invalid_value(self) -> None:
        """A notification, but with a value that does not exist: `PJLinkUnexpectedResponseParameter`."""
        cases = {
            "%2POWR=2\r": "unexpected power status notification",  # Cooling is not a notifiable state.
            "%2POWR=\r": "unexpected power status notification",
            "%2POWR=OK\r": "unexpected power status notification",
            "%2ERST=00000\r": "unexpected number of error types reported",
            "%2ERST=0000000\r": "unexpected number of error types reported",
            "%2ERST=003000\r": "unknown error level",
            "%2INPT=3\r": "expected 2 INPT response characters",
            "%2INPT=311\r": "expected 2 INPT response characters",
            "%2INPT=91\r": "unexpected input source mode",
        }
        for data, message in cases.items():
            with self.subTest(data=data):
                with self.assertRaises(aiopjlink.PJLinkUnexpectedResponseParameter) as err:
                    parse_event(data)
                self.assertEqual(str(err.exception), message)

    def test_events_are_values(self) -> None:
        self.assertEqual(PowerChanged(powered_on=True), PowerChanged(powered_on=True))
        self.assertNotEqual(PowerChanged(powered_on=True), PowerChanged(powered_on=False))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            LinkUp(MAC).mac_address = "aa:bb:cc:dd:ee:ff"  # type: ignore[misc]

    def test_public_api(self) -> None:
        for name in (
            "listen_notifications",
            "Notification",
            "NotificationEvent",
            "LinkUp",
            "ErrorsChanged",
            "PowerChanged",
            "InputChanged",
        ):
            self.assertIn(name, aiopjlink.__all__)


class ListenTests(unittest.IsolatedAsyncioTestCase):
    """The listener yields what projectors send, and only that."""

    async def test_every_kind_of_notification(self) -> None:
        port = unused_udp_port()
        found = await listen_and_send(
            port,
            f"%2LKUP={MAC}\r".encode(),
            b"%2ERST=000000\r",
            b"%2POWR=1\r",
            b"%2INPT=32\r",
            count=4,
        )
        self.assertEqual(
            found,
            [
                Notification(LOCALHOST, LinkUp(MAC)),
                Notification(LOCALHOST, ErrorsChanged(ALL_OK)),
                Notification(LOCALHOST, PowerChanged(powered_on=True)),
                Notification(LOCALHOST, InputChanged(aiopjlink.Sources.Mode.DIGITAL, "2")),
            ],
        )

    async def test_listens_on_every_interface_by_default(self) -> None:
        port = unused_udp_port()
        found = await listen_and_send(port, b"%2POWR=0\r", count=1, local_address=None)
        self.assertEqual(found, [Notification(LOCALHOST, PowerChanged(powered_on=False))])

    async def test_repeated_notification_is_reported_every_time(self) -> None:
        """Unlike a search answer, a repeat can be a real second change (on, off, on): nothing is merged."""
        port = unused_udp_port()
        found = await listen_and_send(port, b"%2POWR=1\r", b"%2POWR=1\r", count=2)
        self.assertEqual(len(found), 2)

    async def test_lenient_notifications(self) -> None:
        port = unused_udp_port()
        found = await listen_and_send(port, b"%2powr=1", b"%2INPT=31\r\n", count=2)
        self.assertEqual(
            [n.event for n in found], [PowerChanged(powered_on=True), InputChanged(aiopjlink.Sources.Mode.DIGITAL, "1")]
        )

    async def test_other_datagrams_are_ignored(self) -> None:
        """Anyone on the network can send to port 4352, and the search protocol uses it as well."""
        junk = (
            b"",
            b"garbage",
            b"\xff\xfe\xfd\r",
            b"%2SRCH\r",  # The search start instruction (e.g. a broadcast looped back).
            f"%2ACKN={MAC}\r".encode(),  # A search response.
            b"%1POWR=1\r",  # Class 1 has no notifications.
            b"%2POWR=2\r",  # A notification with a value that does not exist.
            b"%2ERST=3\r",
            b"%2LKUP=zz\r",
            b"%2XXXX=1\r",
        )
        port = unused_udp_port()
        # An exception in the protocol would not fail the listener: asyncio logs it and carries on.
        with self.assertNoLogs("asyncio", level="ERROR"):
            found = await listen_and_send(port, *junk, b"%2POWR=1\r", count=1)
        self.assertEqual(found, [Notification(LOCALHOST, PowerChanged(powered_on=True))])

    async def test_what_is_ignored_is_logged(self) -> None:
        """So that it can be seen what the projector sends."""
        port = unused_udp_port()
        with self.assertLogs("aiopjlink", level="DEBUG") as logs:
            await listen_and_send(port, b"%2POWR=2\r", b"%2POWR=1\r", count=1)
        output = "\n".join(logs.output)
        self.assertIn("ignoring datagram from 127.0.0.1: unexpected power status notification", output)
        self.assertIn("status notification from 127.0.0.1: PowerChanged(powered_on=True)", output)

    async def test_a_slow_consumer_cannot_use_up_memory(self) -> None:
        """When more are waiting than the queue holds, the newest are dropped: the oldest are the ones kept."""
        queue: asyncio.Queue[Notification] = asyncio.Queue(2)
        protocol = _NotificationProtocol(queue)
        with self.assertLogs("aiopjlink", level="DEBUG") as logs:
            for index in "1234":
                protocol.datagram_received(f"%2INPT=3{index}\r".encode(), (LOCALHOST, 4352))
        self.assertEqual(
            [queue.get_nowait().event for _ in range(2)],
            [
                InputChanged(aiopjlink.Sources.Mode.DIGITAL, "1"),
                InputChanged(aiopjlink.Sources.Mode.DIGITAL, "2"),
            ],
        )
        self.assertTrue(queue.empty())
        self.assertEqual(sum("dropping status notification" in line for line in logs.output), 2)

        # Taking some makes room again.
        protocol.datagram_received(b"%2POWR=1\r", (LOCALHOST, 4352))
        self.assertEqual(queue.get_nowait().event, PowerChanged(powered_on=True))

    async def test_the_listener_bounds_its_queue(self) -> None:
        """What keeps a flood on the open port from filling memory is that the listener's queue has a limit."""
        port = unused_udp_port()
        with mock.patch("aiopjlink._notify.asyncio.Queue", wraps=asyncio.Queue) as queue_class:
            await listen_and_send(port, b"%2POWR=1\r", count=1)
        queue_class.assert_called_once_with(_MAX_PENDING_NOTIFICATIONS)
        self.assertGreater(_MAX_PENDING_NOTIFICATIONS, 0)

    async def test_nothing_happens_before_the_first_iteration(self) -> None:
        port = unused_udp_port()
        listen_notifications(**options(port))
        await asyncio.sleep(0.05)
        # The port is still free: nothing was bound.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((LOCALHOST, port))

    @unittest.skipUnless(ipv6_loopback_available(), "no IPv6 loopback")
    async def test_ipv6(self) -> None:
        port = unused_udp_port()
        found = await listen_and_send(port, b"%2POWR=1\r", count=1, local_address="::1")
        self.assertEqual(found, [Notification("::1", PowerChanged(powered_on=True))])


class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    """The port is given back as soon as the listener is done, so that the next one can use it."""

    async def test_closing_releases_the_port_at_once(self) -> None:
        port = unused_udp_port()
        await listen_and_send(port, b"%2POWR=1\r", count=1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((LOCALHOST, port))

    async def test_cancelling_releases_the_port_at_once(self) -> None:
        port = unused_udp_port()

        async def listen_forever() -> None:
            async for _ in listen_notifications(**options(port)):
                pass

        task = asyncio.create_task(listen_forever())
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((LOCALHOST, port))

    async def test_listening_again_on_the_same_port(self) -> None:
        """Back to back, as when an integration is reloaded: the port is free every time."""
        port = unused_udp_port()
        for _ in range(3):
            found = await listen_and_send(port, b"%2POWR=1\r", count=1)
            self.assertEqual(len(found), 1)

    async def test_socket_is_not_leaked_when_the_loop_cannot_take_it(self) -> None:
        """The port was bound already: whatever goes wrong next, it is given back."""
        port = unused_udp_port()
        with (
            mock.patch.object(asyncio.BaseEventLoop, "create_datagram_endpoint", side_effect=RuntimeError("x")),
            self.assertRaises(RuntimeError),
        ):
            await anext(listen_notifications(**options(port)))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((LOCALHOST, port))


class ListenErrorTests(unittest.IsolatedAsyncioTestCase):
    """What goes wrong on this machine is a `PJLinkNoConnection`; a wrong argument is a `ValueError`."""

    async def test_local_port_in_use(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
            blocker.bind((LOCALHOST, 0))
            port = blocker.getsockname()[1]
            with self.assertRaises(aiopjlink.PJLinkNoConnection) as err:
                await anext(listen_notifications(**options(port)))
        self.assertTrue(str(err.exception).startswith("listening for notifications failed - "), str(err.exception))
        self.assertIsInstance(err.exception, aiopjlink.PJLinkConnectionError)

    async def test_only_one_listener_per_port(self) -> None:
        port = unused_udp_port()
        async with contextlib.aclosing(listen_notifications(**options(port))) as first:
            pending = asyncio.ensure_future(take(first, 1))
            await asyncio.sleep(0)
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await anext(listen_notifications(**options(port)))
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending

    async def test_search_cannot_share_the_port(self) -> None:
        """Both protocols use port 4352 by default, so a search needs another local port while listening."""
        port = unused_udp_port()
        async with contextlib.aclosing(listen_notifications(**options(port))) as found:
            pending = asyncio.ensure_future(take(found, 1))
            await asyncio.sleep(0)
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await aiopjlink.search(
                    duration=0.1, broadcast_address=LOCALHOST, local_address=LOCALHOST, local_port=port
                )
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending

    async def test_local_address_not_on_this_machine(self) -> None:
        with self.assertRaises(aiopjlink.PJLinkNoConnection):
            await anext(listen_notifications(local_address="192.0.2.1", local_port=unused_udp_port()))

    async def test_no_socket_can_be_made(self) -> None:
        """E.g. a machine without IPv6: the listener cannot start, and says so like any other failure."""
        port = unused_udp_port()
        with (
            mock.patch.object(socket, "socket", side_effect=OSError(errno.EAFNOSUPPORT, "not supported")),
            self.assertRaises(aiopjlink.PJLinkNoConnection) as err,
        ):
            await anext(listen_notifications(**options(port)))
        self.assertEqual(
            str(err.exception), f"listening for notifications failed - [Errno {errno.EAFNOSUPPORT}] not supported"
        )

    async def test_undeliverable_datagram_is_no_error(self) -> None:
        """The operating system may report an earlier datagram as undeliverable (ICMP). It is no reason to stop."""
        queue: asyncio.Queue[Notification] = asyncio.Queue()
        _NotificationProtocol(queue).error_received(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        self.assertTrue(queue.empty())

    async def test_invalid_arguments(self) -> None:
        """Rejected before anything is bound."""
        cases: dict[str, dict[str, Any]] = {
            "port is zero": {"local_port": 0},
            "port is negative": {"local_port": -1},
            "port is too large": {"local_port": 65536},
            "address is not an address": {"local_address": "not-an-address"},
            "address is a host name": {"local_address": "localhost"},
            "address is empty": {"local_address": ""},
        }
        for name, overrides in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                await anext(listen_notifications(**options(unused_udp_port(), **overrides)))
