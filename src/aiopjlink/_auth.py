"""_auth.py

The opening handshake of a PJLink connection and its password authentication (§5).

Pure functions only: nothing here touches the network.
"""

import hashlib

from .exceptions import PJLinkPassword, PJLinkProtocolError


def build_request(welcome: str, cstring: str, password: str | None, encoding: str = "utf-8") -> bytes:
    """Turn the projector's welcome line and a command line into the bytes to send (§5.1, §5.2).

    `welcome` is the first line the projector sends after the connection is made:
        * `PJLINK 0` - security is off, the command is sent as it is.
        * `PJLINK 1 <token>` - security is on, the command is prefixed with
          `md5(token + password)` as a hex string.

    Raises `PJLinkProtocolError` if the welcome line is not valid, and `PJLinkPassword`
    if the projector wants a password and none was given.
    """
    if len(welcome) < 9:
        raise PJLinkProtocolError("unexpected opening header message from projector - too short")

    auth_header, auth_enabled, auth_close = welcome[:7], welcome[7], welcome[8]
    if auth_header.upper() != "PJLINK ":
        raise PJLinkProtocolError("unexpected opening header message from projector - not PJLink")

    # No authentication required.
    if auth_enabled == "0":
        return cstring.encode(encoding)

    # Connection requires auth: `PJLINK 1 <token>`.
    if auth_enabled != "1" or auth_close != " ":
        raise PJLinkProtocolError("unexpected opening security message from projector - unrecognised auth method")

    # Check we have a password specified.
    if password is None:
        raise PJLinkPassword("password required")

    # Read the random number used to salt the password (excluding the terminating `\r`).
    token = welcome[9:-1]
    passcode = (token + password).encode("utf-8")
    passcode_md5 = hashlib.md5(passcode).hexdigest()
    return passcode_md5.encode(encoding) + cstring.encode(encoding)
