"""_protocol.py

The wire format of PJLink command and response lines (§2) and of the UDP search
request and response (§3.2.2).

Pure functions only: nothing here touches the network.
"""

import re

from ._debug import LOGGER, redact_debug_payload
from .enums import PJClass
from .exceptions import (
    PJLinkDeviceFailure,
    PJLinkInvalidParameter,
    PJLinkNotReady,
    PJLinkNotSupported,
    PJLinkProtocolError,
)

SEARCH_REQUEST = b"%2SRCH\r"
"""The search start instruction (§3.2.2): `%2SRCH` and CR. It has no separator and no parameter."""

_SEARCH_RESPONSE_PREFIX = "%2ACKN="
_MAC_ADDRESS = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", re.IGNORECASE)


def format_command(command: str, param: str, pjclass: PJClass, encoding: str = "utf-8") -> str:
    """Build a command line: `%<class><COMMAND> <param>\\r` (§2.1).

    The spec limits the command to 4 bytes and the parameter to 128 bytes, so both are measured in
    bytes of `encoding`, the encoding the line is sent in.

    Raises `PJLinkProtocolError` if the command is not four upper-case characters or the
    parameter exceeds 128 bytes, and `ValueError` if `pjclass` is not a valid `PJClass`
    or the text cannot be encoded.
    """
    pjclass = PJClass(pjclass)
    if not command.isupper():
        raise PJLinkProtocolError("command is not uppercase")
    if len(command.encode(encoding)) != 4:
        raise PJLinkProtocolError("command is not 4 bytes")
    if len(param.encode(encoding)) > 128:
        raise PJLinkProtocolError("command param is larger than 128 bytes")
    sep = " "
    return f"%{pjclass.value}{command}{sep}{param}\r"


def parse_response(
    data: str, expect_command: str | None = None, expect_pjclass: PJClass = PJClass.ONE
) -> tuple[str, str]:
    """Split a response line into `(COMMAND, parameter)` (§2.2).

    Raises the matching exception (`PJLinkNotSupported` ... `PJLinkDeviceFailure`) if the projector
    answered with `ERR1` ... `ERR4`, and `PJLinkProtocolError` if the line is not a valid response to
    `expect_command`.
    """
    # NOTE: Postels robustness principle - be conservative in what you do, be liberal in what you accept from others
    LOGGER.debug("received response: %s", redact_debug_payload(data.strip()))
    expect_pjclass = PJClass(expect_pjclass)

    # Shortest valid response: header, class, 4 command characters, separator, CR (e.g. `%1INF2=\r`).
    if len(data) < 8:
        raise PJLinkProtocolError("unexpected response - too short")

    # Check header and class version.
    header, version = data[0], data[1]
    if header != "%":
        raise PJLinkProtocolError("unexpected response header")
    if version != expect_pjclass.value:
        raise PJLinkProtocolError("unexpected response protocol class")

    # Grab the command body, separator, and param.
    command = f"{data[2:6]}".upper()
    sep = data[6]
    param = data[7:-1]

    # Check them for correctness.
    if sep != "=":
        raise PJLinkProtocolError("unexpected response separator")
    if expect_command is not None and command != expect_command:
        raise PJLinkProtocolError("unexpected response command")

    # Handle for protocol and projector errors.
    param_u = param.upper()
    if param_u == "ERR1":
        raise PJLinkNotSupported("unsupported command", command=command)
    if param_u == "ERR2":
        raise PJLinkInvalidParameter("out of parameter", command=command)
    if param_u == "ERR3":
        raise PJLinkNotReady("unavailable in the current state", command=command)
    if param_u == "ERR4":
        raise PJLinkDeviceFailure("projector or display failure", command=command)

    return command, param


def parse_search_response(data: str) -> str:
    """Return the MAC address in a search response, `%2ACKN=xx:xx:xx:xx:xx:xx` and CR (§3.2.2).

    The address is returned in lower case (`aa:bb:cc:dd:ee:ff`), whatever case the projector used.
    A datagram is delimited by the network, so a missing CR (or a CRLF) is accepted.

    Raises `PJLinkProtocolError` if `data` is not a search response.
    """
    line = data.rstrip("\r\n")
    if not line.upper().startswith(_SEARCH_RESPONSE_PREFIX):
        raise PJLinkProtocolError(f"unexpected search response: {line}")
    mac = line[len(_SEARCH_RESPONSE_PREFIX) :]
    if _MAC_ADDRESS.fullmatch(mac) is None:
        raise PJLinkProtocolError(f"unexpected MAC address in search response: {mac}")
    return mac.lower()
