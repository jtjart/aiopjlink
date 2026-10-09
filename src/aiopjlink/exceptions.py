"""exceptions.py

Everything that can go wrong while talking to the projector is raised as a
subclass of `PJLinkException`, so callers only need to catch that one class.
The hierarchy tells a caller what to do about it::

    PJLinkException
    ├── PJLinkConnectionError              projector unreachable or not talking: try again later
    │   ├── PJLinkNoConnection             could not connect, or no greeting / answer in time
    │   └── PJLinkConnectionClosed         connection closed or reset by the projector
    ├── PJLinkPassword                     password missing or wrong
    ├── PJLinkProtocolError                what the projector sent is not valid PJLink
    ├── PJLinkUnexpectedResponseParameter  valid PJLink, but a value this library does not know
    └── PJLinkProjectorError               the projector answered with an error instead of a value
        ├── PJLinkNotSupported             ERR1  command or feature not supported
        ├── PJLinkInvalidParameter         ERR2  parameter out of range
        ├── PJLinkNotReady                 ERR3  unavailable in the current state (standby, warming up, ...)
        └── PJLinkDeviceFailure            ERR4  projector or display failure

Which exception for which situation:

    =====================================================  ================================
    TCP connect refused, DNS failure, connect timeout      `PJLinkNoConnection`
    Connected, but no greeting within the timeout          `PJLinkNoConnection`
    Greeting received, but no response within the timeout  `PJLinkNoConnection`
    Connection closed (FIN) or reset (RST) by the peer     `PJLinkConnectionClosed`
    Password required, rejected (`ERRA`)                   `PJLinkPassword`
    Bytes that are not a valid PJLink line                 `PJLinkProtocolError`
    A valid line with a value the library cannot map       `PJLinkUnexpectedResponseParameter`
    `ERR1` ... `ERR4`                                      `PJLinkNotSupported` ... `PJLinkDeviceFailure`
    =====================================================  ================================

`ERR1` means "undefined command" (§2.3), but the spec reuses it for "this projector has no ...":

    ======  ==================================  =================================
    LAMP ?  no lamp                             `PJLinkNotSupported("no lamp")`
    FILT ?  no filter                           `PJLinkNotSupported("no filter")`
    SVOL    speaker not installed               `PJLinkNotSupported("no speaker installed")`
    MVOL    microphone not installed            `PJLinkNotSupported("no microphone installed")`
    FREZ    freeze not supported                `PJLinkNotSupported("freeze not supported")`
    ======  ==================================  =================================

It is deliberately one class: what ERR1 means is decided by the command that was sent, and the
exception carries that command (`err.command`) and a message that says which of the above applies.
Callers who only care whether a feature exists can use a single `except PJLinkNotSupported`.

`ValueError` is still raised for invalid arguments passed in by the caller
(e.g. an unknown `Power.State`), because that is a programming error.
"""


class PJLinkException(Exception):
    """Base exception for PJLink library issues."""


class PJLinkConnectionError(PJLinkException):
    """The projector cannot be reached, or stopped talking, so no answer was obtained.

    Typical causes are a projector in network standby, one that is rebooting, or one that is
    busy with another controller (many allow a single PJLink session). This is usually
    temporary: treat the projector as unavailable and try again later.

    Never raised directly - catch it to handle `PJLinkNoConnection` and `PJLinkConnectionClosed` together.
    """


class PJLinkNoConnection(PJLinkConnectionError):
    """Could not connect, or the projector did not send a greeting or a response in time."""


class PJLinkConnectionClosed(PJLinkConnectionError):
    """The projector closed or reset the connection."""


class PJLinkProtocolError(PJLinkException):
    """Unexpected communication to or from the projector."""


class PJLinkUnexpectedResponseParameter(PJLinkException):
    """Unable to parse a response parameter."""


class PJLinkPassword(PJLinkException):
    """Invalid or absent password."""


class PJLinkProjectorError(PJLinkException):
    """The projector answered, but with an error (or a condition such as "no signal") instead of a value.

    `command` is the four-letter command the projector answered, when known (e.g. `"SVOL"`).
    """

    def __init__(self, message: str = "", *, command: str | None = None) -> None:
        super().__init__(message)
        self.command = command


class PJLinkNotSupported(PJLinkProjectorError):
    """The projector does not support the command or the feature (spec: `ERR1`, §2.3).

    Some commands give it a specific meaning ("no lamp", "no speaker installed", ...):
    see the module documentation.
    """


class PJLinkInvalidParameter(PJLinkProjectorError):
    """The parameter is out of range, e.g. a nonexistent input source (spec: `ERR2`, §2.3)."""


class PJLinkNotReady(PJLinkProjectorError):
    """The command is not available at the current time or in the current state (spec: `ERR3`, §2.3).

    Typical cases are standby, warming up, cooling down or switching input. Projectors that
    answer a status query with `OK` instead of a value are reported the same way.
    """


class PJLinkDeviceFailure(PJLinkProjectorError):
    """The projector or display has failed and cannot continue to operate properly (spec: `ERR4`, §2.3)."""
