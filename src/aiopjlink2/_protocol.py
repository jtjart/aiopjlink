"""The wire format of PJLink lines (§2) and of the UDP search and notification datagrams (§3.2.2, §3.3.2).

Pure functions only: nothing here touches the network.
"""

import re
from dataclasses import dataclass, field

from ._debug import LOGGER, redact_debug_payload
from .enums import PJClass
from .exceptions import (
    PJLinkInvalidParameterError,
    PJLinkMalfunctionError,
    PJLinkNotReadyError,
    PJLinkNotSupportedError,
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
    """A command line to send: a four-letter command with its parameter, in the format of §2.1.

    Creating one checks the protocol limits: the command is upper case and exactly 4 bytes, and the parameter is
    at most 128 bytes, both counted in `encoding`. `line` is the text to send, ending in CR.

    Args:
        name: Four-letter PJLink command.
        parameter: Command parameter.
        pjclass: PJLink class of the command.
        encoding: Text encoding used to count bytes and format the command.

    Raises:
        PJLinkProtocolError: The command or parameter exceeds the protocol limits.
    """

    name: str
    parameter: str
    pjclass: PJClass

    encoding: str = field(default="utf-8", kw_only=True, repr=False)
    line: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # The dataclass is frozen, so its fields are set through `object.__setattr__`.

        if not self.name.isupper():
            raise PJLinkProtocolError("command is not uppercase")
        if len(self.name.encode(self.encoding)) != _COMMAND_LENGTH:
            raise PJLinkProtocolError("command is not 4 bytes")
        if len(self.parameter.encode(self.encoding)) > _MAX_COMMAND_PARAM_LENGTH:
            raise PJLinkProtocolError("command param is larger than 128 bytes")

        formatted_line = f"%{self.pjclass.value}{self.name} {self.parameter}\r"
        object.__setattr__(self, "line", formatted_line)

    @property
    def is_query(self) -> bool:
        """True for a status query (the parameter starts with `?`). A query changes nothing, so it may be repeated."""
        return self.parameter.startswith("?")


def parse_response(
    response_line: str, expect_command: str | None = None, expect_pjclass: PJClass = PJClass.ONE
) -> tuple[str, str]:
    """Split a response line into `(COMMAND, parameter)` (§2.2).

    `expect_command` and `expect_pjclass` specify the expected command and PJLink class.

    Returns:
        The response command in upper case and its parameter.

    Raises:
        PJLinkProtocolError: The response is malformed or does not match the expected command or PJLink class.
        PJLinkNotSupportedError: The projector returned ERR1.
        PJLinkInvalidParameterError: The projector returned ERR2.
        PJLinkNotReadyError: The projector returned ERR3.
        PJLinkMalfunctionError: The projector returned ERR4.
    """
    LOGGER.debug("received response: %s", redact_debug_payload(response_line.strip()))

    if len(response_line) < _MIN_RESPONSE_LENGTH:
        raise PJLinkProtocolError("unexpected response - too short")

    header_character = response_line[0]
    class_digit = response_line[1]
    command = response_line[2:6].upper()
    separator = response_line[6]
    # Between the separator and the terminating CR.
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
        raise PJLinkNotSupportedError("unsupported command", command=command)
    if parameter_uppercase == "ERR2":
        raise PJLinkInvalidParameterError("out of parameter", command=command)
    if parameter_uppercase == "ERR3":
        raise PJLinkNotReadyError("unavailable in the current state", command=command)
    if parameter_uppercase == "ERR4":
        raise PJLinkMalfunctionError("projector or display failure", command=command)

    return command, parameter


def parse_mac_address(candidate: str) -> str | None:
    """Validate a MAC address and normalise it to lower case.

    Returns:
        The lower-case MAC address, or None if `candidate` is not a valid address.
    """
    return candidate.lower() if _MAC_ADDRESS_PATTERN.fullmatch(candidate) else None


def parse_search_response(datagram_text: str) -> str:
    """Parse a search response datagram (§3.2.2).

    The wire shape is `%2ACKN=xx:xx:xx:xx:xx:xx`. A missing CR (or a CRLF) is accepted because the network
    delimits the datagram.

    Returns:
        The lower-case MAC address.

    Raises:
        PJLinkProtocolError: The datagram is not a valid search response or MAC address.
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

    The parameter is not validated here; its meaning depends on the command. A missing CR (or a CRLF) is accepted
    because the network delimits the datagram. The returned command is in upper case.

    Returns:
        The notification command and parameter.

    Raises:
        PJLinkProtocolError: The datagram is malformed or is not a PJLink 2 notification.
    """
    line = datagram_text.rstrip("\r\n")
    if len(line) < _MIN_RESPONSE_LENGTH or line[:2] != "%2" or line[6] != "=":
        raise PJLinkProtocolError(f"unexpected status notification: {line}")
    return line[2:6].upper(), line[7:]
