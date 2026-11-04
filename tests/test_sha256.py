"""SHA256 authentication (specification 2.10, §5.1) and the fallback to MD5.

`SecureProjector` is a small fake projector with password security. It can do SHA256, MD5 or both, and when it
cannot do SHA256 it reacts to the question `PJLINK 2` in one of the ways the JBMIA "PJLink Class2 Application
Guideline" (§6, behaviours 1 to 7) describes. It checks every digest it receives itself, so a client that
computes it wrongly fails.
"""

import asyncio
import contextlib
import hashlib
import time
import unittest

import aiopjlink
from aiopjlink import PJAuth, Power
from aiopjlink._auth import build_sha256_request, parse_security_reply, parse_welcome
from mock_projector import raw_tcp_server

PASSWORD = "abc123"
TOKEN = "21d0e96e"
NONCE = "3db25e10f69c47a85adb24cf361897e0"

# What a projector without SHA256 may do when asked `PJLINK 2` (guideline §6): behaviour 1 to 7.
LEGACY_BEHAVIOURS = (
    "ERR1",  # 1: undefined command
    "ERR2",  # 2: out of parameter range
    "ERRA",  # 3: password mismatch (but no password was sent!)
    "echo",  # 4: the command is answered as it is: `PJLINK 2`
    "hang up",  # 5: immediate disconnection
    "silent",  # 6 and 7: no answer (6 hangs up after 30 s, longer than any deadline here)
    "bad number",  # not in the guideline: a random number that is not 16 bytes
)


class SecureProjector:
    """A projector with password security that records what it was asked.

    `sha256` / `md5`: which procedures it accepts. `on_inquiry`: what it does with `PJLINK 2` when it has no
    SHA256 (one of `LEGACY_BEHAVIOURS`). `secured=False` makes it greet with `PJLINK 0` and accept anything.
    `drop`: numbers of connections it closes at once, without a greeting. `ignore_inquiries`: how many of the first
    questions it leaves unanswered (a bad moment). `sha256_reject_delay`: seconds it waits before rejecting a
    wrong SHA256 digest, `md5_reject_delay` the same for a wrong MD5 digest (the spec has projectors wait two seconds).
    """

    def __init__(
        self,
        *,
        sha256=True,
        md5=True,
        on_inquiry="ERR1",
        secured=True,
        password=PASSWORD,
        drop=(),
        ignore_inquiries=0,
        sha256_reject_delay=0.0,
        md5_reject_delay=0.0,
        inquiry_delay=0.0,
    ):
        self.drop = set(drop)  # Numbers (from 1) of the connections to close at once, without a greeting.
        self.ignore_inquiries = ignore_inquiries
        self.sha256_reject_delay = sha256_reject_delay
        self.md5_reject_delay = md5_reject_delay
        self.inquiry_delay = inquiry_delay  # Seconds it takes to answer the question.
        self.executed: list[bytes] = []  # The commands it carried out (after a right digest).
        self.sha256 = sha256
        self.md5 = md5
        self.on_inquiry = on_inquiry
        self.secured = secured
        self.password = password
        self.connections = 0
        self.inquiries = 0
        self.lines: list[bytes] = []
        self.authenticated_with: list[str] = []

    async def __call__(self, reader, writer):
        self.connections += 1
        nonce = None
        authenticated = not self.secured
        try:
            if self.connections in self.drop:
                return
            writer.write(f"PJLINK 1 {TOKEN}\r".encode() if self.secured else b"PJLINK 0\r")
            await writer.drain()
            while True:
                line = await reader.readuntil(b"\r")
                self.lines.append(line)

                if line == b"PJLINK 2\r":
                    self.inquiries += 1
                    if self.inquiries <= self.ignore_inquiries:
                        continue
                    await asyncio.sleep(self.inquiry_delay)
                    if self.sha256:
                        nonce = NONCE
                        writer.write(f"PJLINK 2 {NONCE}\r".encode())
                    elif self.on_inquiry in ("ERR1", "ERR2", "ERRA"):
                        writer.write(f"PJLINK {self.on_inquiry}\r".encode())
                    elif self.on_inquiry == "echo":
                        writer.write(b"PJLINK 2\r")
                    elif self.on_inquiry == "bad number":
                        writer.write(b"PJLINK 2 12345\r")
                    elif self.on_inquiry == "hang up":
                        return
                    await writer.drain()
                    continue

                if authenticated:
                    command = line
                else:
                    verified = self._verify(line, nonce)
                    if verified is None:
                        delay = self.sha256_reject_delay if nonce is not None else self.md5_reject_delay
                        if delay:
                            with contextlib.suppress(TimeoutError):
                                # Ends early if the client hangs up.
                                await asyncio.wait_for(reader.read(), delay)
                        writer.write(b"PJLINK ERRA\r")
                        await writer.drain()
                        return
                    command, method = verified
                    self.authenticated_with.append(method)
                    authenticated = True
                self.executed.append(command)
                writer.write(self._answer(command))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def _verify(self, line, nonce):
        """`(command, method)` if the authentication data in front of the command is right, else None."""
        if line.startswith(b"%"):
            return None  # No authentication data at all.
        if nonce is not None:
            mine, digest, command = line[:32], line[32:96], line[96:]
            try:
                mixed = bytes(a ^ b for a, b in zip(bytes.fromhex(nonce), bytes.fromhex(mine.decode()), strict=True))
            except ValueError:
                return None
            expected = hashlib.sha256((mixed.hex() + self.password).encode()).hexdigest().encode()
            return (command, "sha256") if digest == expected else None
        if self.md5:
            digest, command = line[:32], line[32:]
            expected = hashlib.md5((TOKEN + self.password).encode()).hexdigest().encode()
            return (command, "md5") if digest == expected else None
        return None

    @staticmethod
    def _answer(command):
        if command == b"%1POWR ?\r":
            return b"%1POWR=1\r"
        if command == b"%1NAME ?\r":
            return b"%1NAME=Fake\r"
        return b"%1" + command[2:6] + b"=OK\r"


class SpecExampleTests(unittest.TestCase):
    """The pure functions, against the worked example in §5.1 of the specification."""

    PROJECTOR_NONCE = "3db25e10f69c47a85adb24cf361897e0"
    CONTROLLER_NONCE = bytes.fromhex("c14b279e603d8a5f17e849ba360f2dc5")
    DIGEST = b"70ab129eac6924d4c129c9c4fcf45be42e1e776325a66db67e5b6eee50f2a692"

    def test_first_command_of_the_example(self):
        request = build_sha256_request(
            self.PROJECTOR_NONCE, "%1POWR 1\r", "JBMIAProjectorLink", controller_nonce=self.CONTROLLER_NONCE
        )
        self.assertEqual(request, b"c14b279e603d8a5f17e849ba360f2dc5" + self.DIGEST + b"%1POWR 1\r")

    def test_the_controller_number_is_random_and_16_bytes(self):
        first, second = (build_sha256_request(self.PROJECTOR_NONCE, "%1POWR ?\r", "x") for _ in range(2))
        self.assertNotEqual(first[:32], second[:32])
        self.assertEqual(len(first), 32 + 64 + len(b"%1POWR ?\r"))

    def test_upper_case_projector_number_is_accepted(self):
        lower = build_sha256_request(self.PROJECTOR_NONCE, "%1POWR 1\r", "pw", controller_nonce=self.CONTROLLER_NONCE)
        upper = build_sha256_request(
            self.PROJECTOR_NONCE.upper(), "%1POWR 1\r", "pw", controller_nonce=self.CONTROLLER_NONCE
        )
        self.assertEqual(lower, upper)

    def test_security_reply(self):
        self.assertEqual(parse_security_reply(f"PJLINK 2 {NONCE}\r"), NONCE)
        self.assertEqual(parse_security_reply(f"pjlink 2 {NONCE.upper()}\r"), NONCE.upper())
        for bad in (
            "PJLINK ERR1\r",
            "PJLINK ERR2\r",
            "PJLINK ERRA\r",
            "PJLINK 2\r",  # Echo.
            "PJLINK 2 12345\r",  # Too short.
            f"PJLINK 2 {NONCE}00\r",  # Too long.
            f"PJLINK 2 {'g' * 32}\r",  # Not hexadecimal.
            "PJLINK 1 21d0e96e\r",  # The greeting again.
            "%1POWR=1\r",
            "",
        ):
            with self.subTest(reply=bad):
                self.assertIsNone(parse_security_reply(bad))

    def test_welcome(self):
        self.assertTrue(parse_welcome("PJLINK 1 21d0e96e\r").secured)
        self.assertFalse(parse_welcome("PJLINK 0\r").secured)
        for bad in ("PJLINK\r", "PJLINK X\r", "PJLINK 1X21d0e96e\r", "PJLINK 2 21d0e96e\r", "HELLO WORLD\r"):
            with self.subTest(welcome=bad), self.assertRaises(aiopjlink.PJLinkProtocolError):
                parse_welcome(bad)


class Sha256Tests(unittest.IsolatedAsyncioTestCase):
    """A projector that supports SHA256."""

    async def test_one_digest_per_connection(self):
        """§5.1 and §5.3: the question and the digest start the connection, later commands go out as they are."""
        projector = SecureProjector(md5=False)
        async with raw_tcp_server(projector) as server, server.client(password=PASSWORD, timeout=2) as link:
            self.assertEqual(await link.power.get(), Power.State.ON)
            self.assertEqual(await link.info.projector_name(), "Fake")
        self.assertEqual(projector.connections, 1)
        self.assertEqual(projector.authenticated_with, ["sha256"])
        self.assertEqual(projector.lines[0], b"PJLINK 2\r")
        self.assertEqual(len(projector.lines[1]), 32 + 64 + len(b"%1POWR ?\r"))
        self.assertEqual(projector.lines[2], b"%1NAME ?\r")

    async def test_every_command_of_a_non_persistent_link_does_the_handshake(self):
        projector = SecureProjector(md5=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2, persistent=False)
            for _ in range(3):
                self.assertEqual(await link.power.get(), Power.State.ON)
        self.assertEqual(projector.connections, 3)
        self.assertEqual(projector.inquiries, 3)
        self.assertEqual(projector.authenticated_with, ["sha256"] * 3)

    async def test_wrong_password(self):
        """`ERRA` for a digest is a password error, and the link does not retry with MD5."""
        projector = SecureProjector(md5=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=2)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
        self.assertEqual(projector.connections, 1)

    async def test_missing_password_is_reported_before_anything_is_asked(self):
        projector = SecureProjector()
        async with raw_tcp_server(projector) as server:
            with self.assertRaises(aiopjlink.PJLinkPassword) as err:
                await server.client(timeout=2).power.get()
        self.assertEqual(str(err.exception), "password required")
        self.assertEqual(projector.lines, [])

    async def test_projector_without_security_is_not_asked(self):
        projector = SecureProjector(secured=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.lines, [b"%1POWR ?\r"])

    async def test_sha256_only_mode_with_a_sha256_projector(self):
        projector = SecureProjector(md5=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2, authentication=PJAuth.SHA256)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.authenticated_with, ["sha256"])


class LegacyFallbackTests(unittest.IsolatedAsyncioTestCase):
    """§5.1: a projector without SHA256 is reached with MD5 on a new connection, whatever it did with `PJLINK 2`."""

    async def test_every_behaviour_ends_in_md5_and_is_remembered(self):
        for behaviour in LEGACY_BEHAVIOURS:
            with self.subTest(behaviour=behaviour):
                projector = SecureProjector(sha256=False, on_inquiry=behaviour)
                async with raw_tcp_server(projector) as server:
                    link = server.client(password=PASSWORD, timeout=2)

                    start = time.monotonic()
                    self.assertEqual(await link.power.get(), Power.State.ON)
                    self.assertLess(time.monotonic() - start, 2)  # Within the deadline, even for a silent one.
                    # Asked once, then the connection was replaced (not reused: the guideline says to start over).
                    self.assertEqual((projector.inquiries, projector.connections), (1, 2))

                    # The kept connection carries the next command without further ado.
                    self.assertEqual(await link.power.get(), Power.State.ON)
                    self.assertEqual((projector.inquiries, projector.connections), (1, 2))

                    # A new connection no longer asks: MD5 is known to work.
                    await link.close()
                    self.assertEqual(await link.power.get(), Power.State.ON)
                    self.assertEqual((projector.inquiries, projector.connections), (1, 3))
                    await link.close()
                self.assertEqual(projector.authenticated_with, ["md5", "md5"])

    async def test_erra_to_the_question_is_not_a_password_error(self):
        """Behaviour 3 looks exactly like a wrong password, but nothing was sent that could be wrong."""
        projector = SecureProjector(sha256=False, on_inquiry="ERRA")
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()

    async def test_wrong_password_on_a_legacy_projector_is_still_a_password_error(self):
        projector = SecureProjector(sha256=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=2)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()

    async def test_sha256_only_mode_never_downgrades(self):
        for behaviour in LEGACY_BEHAVIOURS:
            with self.subTest(behaviour=behaviour):
                projector = SecureProjector(sha256=False, on_inquiry=behaviour)
                async with raw_tcp_server(projector) as server:
                    link = server.client(password=PASSWORD, timeout=2, authentication=PJAuth.SHA256)
                    with self.assertRaises(aiopjlink.PJLinkNotSupported):
                        await link.power.get()
                self.assertEqual(projector.authenticated_with, [])
                self.assertEqual([line for line in projector.lines if line != b"PJLINK 2\r"], [])

    async def test_a_remembered_md5_that_is_rejected_is_replaced_by_sha256_at_once(self):
        """MD5 stops working (the projector was switched to SHA256): the same command asks again and succeeds."""
        projector = SecureProjector(sha256=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            self.assertEqual(await link.power.get(), Power.State.ON)  # Learns MD5.
            await link.close()

            projector.sha256, projector.md5 = True, False
            await link.power.turn_on()  # Rejected with MD5 on the new connection, then done with SHA256.
            self.assertEqual(projector.executed.count(b"%1POWR 1\r"), 1)  # Carried out once, not twice.
            await link.close()
            self.assertEqual(projector.inquiries, 2)

            # SHA256 is what is remembered now: the next connection asks, and uses SHA256.
            await link.power.get()
            await link.close()
        self.assertEqual(projector.authenticated_with, ["md5", "sha256", "sha256"])
        self.assertEqual(projector.inquiries, 3)

    async def test_unanswered_question_then_md5_rejected_asks_again_at_once(self):
        """A SHA256 projector that missed the question: MD5 is rejected, and the second try works."""
        projector = SecureProjector(sha256=True, md5=False, ignore_inquiries=1)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=3)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.authenticated_with, ["sha256"])
        self.assertEqual((projector.inquiries, projector.connections), (2, 3))

    async def test_a_projector_that_said_no_is_not_asked_again_after_a_wrong_password(self):
        projector = SecureProjector(sha256=False, on_inquiry="ERR1")
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=3)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
        self.assertEqual((projector.inquiries, projector.connections), (1, 2))

    async def test_wrong_password_on_a_silent_projector_is_a_password_error(self):
        """Both tries fail within the deadline; the result is `PJLinkPassword`, not a timeout."""
        projector = SecureProjector(sha256=False, on_inquiry="silent")
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=2)
            start = time.monotonic()
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
            self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(projector.inquiries, 2)
        # The second try is for SHA256 only: just one MD5 digest was ever sent.
        self.assertEqual(len([line for line in projector.lines if line != b"PJLINK 2\r"]), 1)

    async def test_the_second_try_does_not_depend_on_the_timeout(self):
        """Even with a very short `timeout` the second try happens: it has a deadline of its own."""
        projector = SecureProjector(sha256=True, md5=False, ignore_inquiries=1, inquiry_delay=0.2)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=1)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.authenticated_with, ["sha256"])

    async def test_a_wrong_password_is_a_password_error_even_with_a_short_timeout(self):
        """§5.1: a projector answers a wrong digest after two seconds. That is `PJLinkPassword`, whatever `timeout`."""
        for name, projector in (
            ("md5", SecureProjector(sha256=False, on_inquiry="ERR1", password="right", md5_reject_delay=1.5)),
            ("sha256", SecureProjector(md5=False, password="right", sha256_reject_delay=1.5)),
        ):
            with self.subTest(procedure=name):
                async with raw_tcp_server(projector) as server:
                    link = server.client(password="wrong", timeout=1)
                    with self.assertRaises(aiopjlink.PJLinkPassword):
                        await link.power.get()

    async def test_wrong_password_on_the_second_try_is_a_password_error_not_a_timeout(self):
        """The projector sits on a wrong SHA256 digest past the deadline (§5.1: two seconds): still `PJLinkPassword`."""
        projector = SecureProjector(
            sha256=True, md5=False, ignore_inquiries=1, sha256_reject_delay=10, password="right"
        )
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=3)
            start = time.monotonic()
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
            self.assertLess(time.monotonic() - start, 6)

    async def test_sha256_only_mode_has_no_second_try(self):
        projector = SecureProjector(sha256=True, md5=False, password="right")
        async with raw_tcp_server(projector) as server:
            link = server.client(password="wrong", timeout=2, authentication=PJAuth.SHA256)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
        self.assertEqual(projector.connections, 1)

    async def test_silence_is_remembered_so_a_projector_is_not_asked_again_and_again(self):
        """Silence, then the new connection is dropped: MD5 is assumed, and the next command does not ask again.

        A projector that cannot cope with the question (guideline behaviour 6: it hangs up only after 30 s, and
        takes no other connection meanwhile) would otherwise be put out of action by every new connection.
        """
        projector = SecureProjector(sha256=False, on_inquiry="silent", drop={2})
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                await link.power.get()
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.inquiries, 1)
        self.assertEqual(projector.authenticated_with, ["md5"])

    async def test_a_sha256_projector_that_missed_the_question_is_put_right(self):
        """MD5 is assumed after silence; if that projector turns out to do SHA256 the next command finds out."""
        projector = SecureProjector(sha256=True, md5=False, ignore_inquiries=1, drop={2})
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            with self.assertRaises(aiopjlink.PJLinkConnectionClosed):
                await link.power.get()
            self.assertEqual(await link.power.get(), Power.State.ON)  # MD5 rejected, SHA256 at once.
            await link.close()
        self.assertEqual(projector.authenticated_with, ["sha256"])

    async def test_a_rejected_password_does_not_poison_the_link(self):
        """Once the password is right (it was changed on the projector), the same link works again."""
        projector = SecureProjector(sha256=False, on_inquiry="silent", password="other")
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()
            projector.password = PASSWORD
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.authenticated_with, ["md5"])


class DigestAnswerTimeTests(unittest.IsolatedAsyncioTestCase):
    """A command with a digest gets at least 3 s to be answered (a projector may wait 2 s before rejecting it)."""

    async def test_silence_after_a_digest_is_a_timeout_after_about_three_seconds(self):
        async def deaf(reader, writer):
            writer.write(f"PJLINK 1 {TOKEN}\r".encode())
            await writer.drain()
            await reader.read()  # Takes everything, answers nothing.
            writer.close()

        async with raw_tcp_server(deaf) as server:
            link = server.client(password=PASSWORD, timeout=1, authentication=PJAuth.MD5)
            start = time.monotonic()
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await link.power.get()
            self.assertGreater(time.monotonic() - start, 2.5)
            self.assertLess(time.monotonic() - start, 4)

    async def test_no_digest_no_extra_time(self):
        """Without a password the deadline is `timeout`, as it always was."""

        async def deaf(reader, writer):
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            await reader.read()
            writer.close()

        async with raw_tcp_server(deaf) as server:
            link = server.client(timeout=1)
            start = time.monotonic()
            with self.assertRaises(aiopjlink.PJLinkNoConnection):
                await link.power.get()
            self.assertLess(time.monotonic() - start, 2)


class ModeTests(unittest.IsolatedAsyncioTestCase):
    """`authentication` chooses the procedure."""

    async def test_md5_mode_never_asks(self):
        projector = SecureProjector(sha256=True, md5=True)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2, authentication=PJAuth.MD5)
            self.assertEqual(await link.power.get(), Power.State.ON)
            await link.close()
        self.assertEqual(projector.inquiries, 0)
        self.assertEqual(projector.authenticated_with, ["md5"])

    async def test_md5_mode_against_a_sha256_only_projector(self):
        projector = SecureProjector(sha256=True, md5=False)
        async with raw_tcp_server(projector) as server:
            link = server.client(password=PASSWORD, timeout=2, authentication=PJAuth.MD5)
            with self.assertRaises(aiopjlink.PJLinkPassword):
                await link.power.get()

    async def test_default_is_auto(self):
        self.assertIs(aiopjlink.PJLink(address="127.0.0.1").authentication, PJAuth.AUTO)

    async def test_strings_are_accepted(self):
        self.assertIs(aiopjlink.PJLink(address="127.0.0.1", authentication="sha256").authentication, PJAuth.SHA256)
        self.assertIs(aiopjlink.PJLink(address="127.0.0.1", authentication=PJAuth.MD5).authentication, PJAuth.MD5)

    async def test_unknown_mode_is_a_value_error(self):
        with self.assertRaises(ValueError):
            aiopjlink.PJLink(address="127.0.0.1", authentication="sha512")

    async def test_exported(self):
        self.assertIn("PJAuth", aiopjlink.__all__)
