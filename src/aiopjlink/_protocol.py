"""_protocol.py

The wire format of PJLink command and response lines (§2), of the UDP search
request and response (§3.2.2) and of the UDP status notifications (§3.3.2).

Pure functions only: nothing here touches the network.
"""

import re
from dataclasses import dataclass, field

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
_MAC_ADDRESS_PATTERN = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", re.IGNORECASE)
_COMMAND_LENGTH = 4
_MAX_COMMAND_PARAM_LENGTH = 128
_MIN_RESPONSE_LENGTH = 8


@dataclass(frozen=True, slots=True)
class PJCommand:
    name: str
    parameter: str
    pjclass: PJClass

    encoding: str = field(default="utf-8", kw_only=True, repr=False)
    line: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pjclass", PJClass(self.pjclass))

        if not self.name.isupper():
            raise PJLinkProtocolError("command is not uppercase")
        if len(self.name.encode(self.encoding)) != _COMMAND_LENGTH:
            raise PJLinkProtocolError("command is not 4 bytes")
        if len(self.parameter.encode(self.encoding)) > _MAX_COMMAND_PARAM_LENGTH:
            raise PJLinkProtocolError("command param is larger than 128 bytes")

        formatted_line = f"%{self.pjclass.value}{self.name} {self.parameter}\r"
        object.__setattr__(self, "line", formatted_line)


def parse_response(
    response_line: str, expect_command: str | None = None, expect_pjclass: PJClass = PJClass.ONE
) -> tuple[str, str]:
    """Split a response line into `(COMMAND, parameter)` (§2.2)."""
    LOGGER.debug("received response: %s", redact_debug_payload(response_line.strip()))

    if len(response_line) < _MIN_RESPONSE_LENGTH:
        raise PJLinkProtocolError("unexpected response - too short")

    header_character = response_line[0]
    class_digit = response_line[1]
    command = response_line[2:6].upper()
    separator = response_line[6]
    parameter = response_line[7:-1]

    if header_character != "%":
        raise PJLinkProtocolError("unexpected response header")
    if class_digit != expect_pjclass.value:
        raise PJLinkProtocolError("unexpected response protocol class")
    if separator != "=":
        raise PJLinkProtocolError("unexpected response separator")
    if expect_command is not None and command != expect_command:
        raise PJLinkProtocolError("unexpected response command")

    parameter_uppercase = parameter.upper()
    if parameter_uppercase == "ERR1":
        raise PJLinkNotSupported("unsupported command", command=command)
    if parameter_uppercase == "ERR2":
        raise PJLinkInvalidParameter("out of parameter", command=command)
    if parameter_uppercase == "ERR3":
        raise PJLinkNotReady("unavailable in the current state", command=command)
    if parameter_uppercase == "ERR4":
        raise PJLinkDeviceFailure("projector or display failure", command=command)

    return command, parameter


def parse_mac_address(candidate: str) -> str | None:
    """Return `candidate` as a lower-case MAC address (`aa:bb:cc:dd:ee:ff`), or None if it is not one."""
    return candidate.lower() if _MAC_ADDRESS_PATTERN.fullmatch(candidate) else None


def parse_search_response(datagram_text: str) -> str:
    """Return the MAC address in a search response, `%2ACKN=xx:xx:xx:xx:xx:xx` and CR (§3.2.2).

    The address is returned in lower case (`aa:bb:cc:dd:ee:ff`), whatever case the projector used.
    A datagram is delimited by the network, so a missing CR (or a CRLF) is accepted.
    """
    line = datagram_text.rstrip("\r\n")
    if not line.upper().startswith(_SEARCH_RESPONSE_PREFIX):
        raise PJLinkProtocolError(f"unexpected search response: {line}")
    mac_address = parse_mac_address(line[len(_SEARCH_RESPONSE_PREFIX) :])
    if mac_address is None:
        raise PJLinkProtocolError("unexpected MAC address in search response")
    return mac_address


def split_notification(datagram_text: str) -> tuple[str, str]:
    """Split a status notification, `%2<COMMAND>=<parameter>` and CR (§3.3.2), into `(COMMAND, parameter)`.

    The command is returned in upper case, whatever case the projector used. What the parameter means is up
    to the command, so it is not looked at here. A datagram is delimited by the network, so a missing CR (or a
    CRLF) is accepted, as it is for the search response.

    """
    line = datagram_text.rstrip("\r\n")
    if len(line) < _MIN_RESPONSE_LENGTH or line[:2] != "%2" or line[6] != "=":
        raise PJLinkProtocolError(f"unexpected status notification: {line}")
    return line[2:6].upper(), line[7:]
