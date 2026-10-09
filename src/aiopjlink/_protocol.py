"""_protocol.py

The wire format of PJLink command and response lines (§2).

Pure functions only: nothing here touches the network.
"""

from ._debug import LOGGER, redact_debug_payload
from .enums import PJClass
from .exceptions import (
    PJLinkDeviceFailure,
    PJLinkInvalidParameter,
    PJLinkNotReady,
    PJLinkNotSupported,
    PJLinkProtocolError,
)


def format_command(command: str, param: str, pjclass: PJClass) -> str:
    """Build a command line: `%<class><COMMAND> <param>\\r` (§2.1).

    Raises `PJLinkProtocolError` if the command is not four upper-case characters or the
    parameter exceeds 128 bytes, and `ValueError` if `pjclass` is not a valid `PJClass`.
    """
    pjclass = PJClass(pjclass)
    if not command.isupper():
        raise PJLinkProtocolError("command is not uppercase")
    if len(command) != 4:
        raise PJLinkProtocolError("command is not 4 bytes")
    if len(param) > 128:
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
