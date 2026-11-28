"""The opening handshake of a PJLink connection and its password authentication (§5).

Pure functions only: nothing here touches the network.
"""

import hashlib
import re
import secrets

from .exceptions import PJLinkAuthenticationError, PJLinkProtocolError

SHA256_INQUIRY = "PJLINK 2\r"
"""The controller's question after the greeting: which security level does the projector support? (§5.1, (1-2))"""

_SHA256_NONCE_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
_SHA256_REPLY_FIELD_COUNT = 3
_MIN_WELCOME_LENGTH = 9


def authentication_required(welcome_line: str) -> bool:
    """Check the welcome line and say whether it wants a password (§5.1, §5.2).

    Returns:
        Whether the welcome line requests password authentication.

    Raises:
        PJLinkProtocolError: The welcome line is not a supported PJLink greeting.
    """
    if len(welcome_line) < _MIN_WELCOME_LENGTH:
        raise PJLinkProtocolError("unexpected opening header message from projector - too short")

    greeting_prefix, security_flag, separator = welcome_line[:7], welcome_line[7], welcome_line[8]
    if greeting_prefix.upper() != "PJLINK ":
        raise PJLinkProtocolError("unexpected opening header message from projector - not PJLink")

    if security_flag == "0":
        return False

    # `PJLINK 1 <token>` is the only other greeting the spec defines.
    if security_flag != "1" or separator != " ":
        raise PJLinkProtocolError("unexpected opening security message from projector - unrecognised auth method")

    return True


def build_md5_request(welcome_line: str, command_line: str, password: str | None, encoding: str = "utf-8") -> bytes:
    """Turn the projector's welcome line and a command line into the bytes to send (§5.1, §5.2).

    Returns:
        The command line, with the MD5 authentication digest prepended when required.

    Raises:
        PJLinkProtocolError: The welcome line is invalid.
        PJLinkAuthenticationError: Password authentication is required but no password was supplied.
    """
    if not authentication_required(welcome_line):
        return command_line.encode(encoding)

    if password is None:
        raise PJLinkAuthenticationError("password required")

    # Read the random number used to salt the password (excluding the terminating `\r`).
    token = welcome_line[9:-1]
    salted_password = (token + password).encode("utf-8")
    # PJLink authentication is specified as MD5(token + password); keep for protocol compatibility.
    digest = hashlib.md5(salted_password, usedforsecurity=False).hexdigest()
    return digest.encode(encoding) + command_line.encode(encoding)


def parse_security_reply(reply: str) -> str | None:
    """Read the projector's answer to `SHA256_INQUIRY` (§5.1, (1-3)).

    Returns:
        The projector's 32-hex-character random number, or None if the reply is not a valid SHA256 response.

    The projector does not support SHA256 if it answers `ERR1`, `ERR2`, `ERRA`, or echoes the question, or if its
    random number is not 16 bytes (32 hexadecimal characters).
    """
    fields = reply.strip().split(" ")
    if (
        len(fields) == _SHA256_REPLY_FIELD_COUNT
        and fields[0].upper() == "PJLINK"
        and fields[1] == "2"
        and _SHA256_NONCE_PATTERN.fullmatch(fields[2])
    ):
        return fields[2]
    return None


def build_sha256_request(projector_nonce: str, command_line: str, password: str, encoding: str = "utf-8") -> bytes:
    """Build the first command bytes for a SHA256-authenticated connection (§5.1, (1-4) and (1-5)).

    The digest uses the XOR of the projector and controller nonces followed by the password.
    The controller's number goes in front of the digest so the projector can combine them the same way.

    Args:
        projector_nonce: The 32-hex-character nonce returned by the projector.
        command_line: The PJLink command line to send.
        password: The projector password.
        encoding: The encoding used for the outgoing bytes.

    Returns:
        The controller nonce and SHA256 digest, followed by the command line.
    """
    own_nonce = secrets.token_bytes(16)
    combined_nonce = bytes(
        projector_byte ^ controller_byte
        for projector_byte, controller_byte in zip(bytes.fromhex(projector_nonce), own_nonce, strict=True)
    )
    digest = hashlib.sha256((combined_nonce.hex() + password).encode("utf-8")).hexdigest()
    return (own_nonce.hex() + digest).encode(encoding) + command_line.encode(encoding)
