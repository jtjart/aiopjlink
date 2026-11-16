"""Everything that can go wrong while talking to the projector is raised as a subclass of `PJLinkError`.

Callers only need to catch that one class. The hierarchy tells them what to do about it::

    PJLinkError
    ├── PJLinkConnectionError            projector unreachable or not talking: try again later
    │   ├── PJLinkNoConnectionError      could not connect, or no greeting / answer in time, or no UDP socket
    │   └── PJLinkConnectionClosedError  connection closed or reset by the projector
    ├── PJLinkAuthenticationError        password missing or wrong
    ├── PJLinkProtocolError              what the projector sent is not valid PJLink
    ├── PJLinkUnexpectedValueError       valid PJLink, but a value this library does not know
    └── PJLinkProjectorError             the projector answered with an error instead of a value
        ├── PJLinkNotSupportedError      ERR1  command or feature not supported
        ├── PJLinkInvalidParameterError  ERR2  parameter out of range
        ├── PJLinkNotReadyError          ERR3  unavailable in the current state (standby, warming up, ...)
        └── PJLinkMalfunctionError       ERR4  projector or display failure

Which exception for which situation:

    =====================================================  ================================
    TCP connect refused, DNS failure, connect timeout      `PJLinkNoConnectionError`
    Connected, but no greeting within the timeout          `PJLinkNoConnectionError`
    Greeting received, but no response within the timeout  `PJLinkNoConnectionError`
    Search, listen: UDP socket cannot be opened or bound   `PJLinkNoConnectionError`
    Connection closed (FIN) or reset (RST) by the peer     `PJLinkConnectionClosedError`
    Password required, rejected (`ERRA`)                   `PJLinkAuthenticationError`
    Hang-up after the first password                       `PJLinkAuthenticationError`
    SHA256 required but not offered by the projector       `PJLinkNotSupportedError`
    Bytes that are not a valid PJLink line                 `PJLinkProtocolError`
    A valid line with a value the library cannot map       `PJLinkUnexpectedValueError`
    `ERR1` ... `ERR4`                                      `PJLinkNotSupportedError` ... `PJLinkMalfunctionError`
    =====================================================  ================================

`ERR1` means "undefined command" (§2.3), but the spec reuses it for "this projector has no ...":

    ======  ==================================  =================================
    LAMP ?  no lamp                             `PJLinkNotSupportedError("no lamp")`
    FILT ?  no filter                           `PJLinkNotSupportedError("no filter")`
    SVOL    speaker not installed               `PJLinkNotSupportedError("no speaker installed")`
    MVOL    microphone not installed            `PJLinkNotSupportedError("no microphone installed")`
    FREZ    freeze not supported                `PJLinkNotSupportedError("freeze not supported")`
    ======  ==================================  =================================

It is deliberately one class: what ERR1 means is decided by the command that was sent, and the
exception carries that command (`err.command`) and a message that says which of the above applies.
Callers who only care whether a feature exists can use a single `except PJLinkNotSupportedError`.

`ValueError` is still raised for invalid arguments passed in by the caller
(e.g. an unknown `Power.State`), because that is a programming error.
"""


class PJLinkError(Exception):
    """Base exception for PJLink library issues."""


class PJLinkConnectionError(PJLinkError):
    """The projector cannot be reached, or stopped talking, so no answer was obtained.

    Typical causes are a projector in network standby, one that is rebooting, or one that is
    busy with another controller (many allow a single PJLink session). This is usually
    temporary: treat the projector as unavailable and try again later.

    Never raised directly - catch it to handle `PJLinkNoConnectionError` and `PJLinkConnectionClosedError` together.
    """


class PJLinkNoConnectionError(PJLinkConnectionError):
    """Could not connect, or the projector did not send a greeting or a response in time.

    Also raised by `search` when the network is not there to search: the UDP socket cannot be opened or bound
    (e.g. the local port is in use), or the search request cannot be sent anywhere. The message says
    `search failed - ...` and carries the reason. `listen_notifications` raises it when its UDP socket cannot be
    opened or bound, with `listening for notifications failed - ...`.
    """


class PJLinkConnectionClosedError(PJLinkConnectionError):
    """The projector closed or reset the connection."""


class PJLinkProtocolError(PJLinkError):
    """Unexpected communication to or from the projector."""


class PJLinkUnexpectedValueError(PJLinkError):
    """Unable to parse a response parameter."""


class PJLinkAuthenticationError(PJLinkError):
    """Invalid or absent password.

    Also raised when a projector that has never accepted the password closes the connection right after
    receiving it (some projectors might do that instead of sending `ERRA`).
    """


class PJLinkProjectorError(PJLinkError):
    """The projector answered, but with an error (or a condition such as "no signal") instead of a value.

    `command` is the four-letter command the projector answered, when known (e.g. `"SVOL"`).
    """

    def __init__(self, message: str = "", *, command: str | None = None) -> None:
        super().__init__(message)
        self.command = command


class PJLinkNotSupportedError(PJLinkProjectorError):
    """The projector does not support the command or the feature (spec: `ERR1`, §2.3).

    Some commands give it a specific meaning ("no lamp", "no speaker installed", ...):
    see the module documentation.

    Also raised, with no `command`, when `PJAuth.SHA256` is required and the projector does not support it.
    """


class PJLinkInvalidParameterError(PJLinkProjectorError):
    """The parameter is out of range, e.g. a nonexistent input source (spec: `ERR2`, §2.3)."""


class PJLinkNotReadyError(PJLinkProjectorError):
    """The command is not available at the current time or in the current state (spec: `ERR3`, §2.3).

    Typical cases are standby, warming up, cooling down or switching input. Projectors that
    answer a status query with `OK` instead of a value are reported the same way.
    """


class PJLinkMalfunctionError(PJLinkProjectorError):
    """The projector or display has failed and cannot continue to operate properly (spec: `ERR4`, §2.3)."""
