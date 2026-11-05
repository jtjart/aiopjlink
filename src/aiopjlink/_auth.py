"""_auth.py

The opening handshake of a PJLink connection and its password authentication (§5).

Pure functions only: nothing here touches the network.
"""

import hashlib
import re
import secrets
from typing import NamedTuple

from .exceptions import PJLinkPassword, PJLinkProtocolError

SHA256_INQUIRY = "PJLINK 2\r"
"""The controller's question after the greeting: which security level does the projector support? (§5.1, (1-2))"""

_SHA256_NONCE = re.compile(r"[0-9a-fA-F]{32}")


class Welcome(NamedTuple):
    """What the projector's first line says."""

    secured: bool
    """True if the projector wants a password (`PJLINK 1 <token>`), False for `PJLINK 0`."""


def parse_welcome(welcome: str) -> Welcome:
    """Check the projector's welcome line (§5.1, §5.2) and say whether it wants a password.

    Raises `PJLinkProtocolError` if the line is not valid.
    """
    if len(welcome) < 9:
        raise PJLinkProtocolError("unexpected opening header message from projector - too short")

    auth_header, auth_enabled, auth_close = welcome[:7], welcome[7], welcome[8]
    if auth_header.upper() != "PJLINK ":
        raise PJLinkProtocolError("unexpected opening header message from projector - not PJLink")

    # No authentication required.
    if auth_enabled == "0":
        return Welcome(secured=False)

    # Connection requires auth: `PJLINK 1 <token>`.
    if auth_enabled != "1" or auth_close != " ":
        raise PJLinkProtocolError("unexpected opening security message from projector - unrecognised auth method")

    return Welcome(secured=True)


def build_request(welcome: str, cstring: str, password: str | None, encoding: str = "utf-8") -> bytes:
    """Turn the projector's welcome line and a command line into the bytes to send (§5.1, §5.2).

    `welcome` is the first line the projector sends after the connection is made:
        * `PJLINK 0` - security is off, the command is sent as it is.
        * `PJLINK 1 <token>` - security is on, the command is prefixed with
          `md5(token + password)` as a hex string.

    This is the MD5 procedure; for SHA256 see `build_sha256_request`.

    Raises `PJLinkProtocolError` if the welcome line is not valid, and `PJLinkPassword`
    if the projector wants a password and none was given.
    """
    if not parse_welcome(welcome).secured:
        return cstring.encode(encoding)

    # Check we have a password specified.
    if password is None:
        raise PJLinkPassword("password required")

    # Read the random number used to salt the password (excluding the terminating `\r`).
    token = welcome[9:-1]
    passcode = (token + password).encode("utf-8")
    # PJLink authentication is specified as MD5(token + password); keep for protocol compatibility.
    passcode_md5 = hashlib.md5(passcode, usedforsecurity=False).hexdigest()
    return passcode_md5.encode(encoding) + cstring.encode(encoding)


def parse_security_reply(reply: str) -> str | None:
    """Read the projector's answer to `SHA256_INQUIRY` (§5.1, (1-3)).

    Returns the projector's random number (32 hex characters) if it supports SHA256, and None for anything else:
    `ERR1`, `ERR2`, `ERRA`, an echo of the question, a random number that is not 16 bytes, ... The spec treats
    every one of them as "does not support SHA256".
    """
    parts = reply.strip().split(" ")
    if len(parts) == 3 and parts[0].upper() == "PJLINK" and parts[1] == "2" and _SHA256_NONCE.fullmatch(parts[2]):
        return parts[2]
    return None


def build_sha256_request(
    projector_nonce: str,
    cstring: str,
    password: str,
    encoding: str = "utf-8",
    *,
    controller_nonce: bytes | None = None,
) -> bytes:
    """The bytes to send for the first command of a SHA256 connection (§5.1, (1-4) and (1-5)).

    `projector_nonce` is the 32 hex characters the projector answered with. A random number of our own (16 bytes,
    `controller_nonce`, only fixed by tests) is XORed with it; the digest is
    `sha256(hex(xor) + password)`, and the line is `hex(our number) + digest + command`.
    """
    ours = secrets.token_bytes(16) if controller_nonce is None else controller_nonce
    mixed = bytes(a ^ b for a, b in zip(bytes.fromhex(projector_nonce), ours, strict=True))
    digest = hashlib.sha256((mixed.hex() + password).encode("utf-8")).hexdigest()
    return (ours.hex() + digest).encode(encoding) + cstring.encode(encoding)
