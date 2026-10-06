"""exceptions.py

Everything that can go wrong while talking to the projector is raised as a
subclass of `PJLinkException`, so callers only need to catch that one class:

    * `PJLinkNoConnection`: could not connect, or the projector did not answer in time.
    * `PJLinkConnectionClosed`: the connection was closed or reset mid-command.
    * `PJLinkPassword`: password missing or wrong.
    * `PJLinkProtocolError`: the projector sent something that is not valid PJLink.
    * `PJLinkUnexpectedResponseParameter`: valid PJLink, but an unexpected value.
    * `PJLinkERR1` ... `PJLinkERR4`, `PJLinkProjectorError`: the projector reported an error.

`ValueError` is still raised for invalid arguments passed in by the caller
(e.g. an unknown `Power.State`), because that is a programming error.
"""


class PJLinkException(Exception):
    """Base exception for PJLink library issues."""


class PJLinkNoConnection(PJLinkException):
    """Projector did not respond to the connection request (or to a command, in time)."""


class PJLinkConnectionClosed(PJLinkException):
    """Projector closed the connection."""


class PJLinkProtocolError(PJLinkException):
    """Unexpected communication to or from the projector."""


class PJLinkUnexpectedResponseParameter(PJLinkException):
    """Unable to parse a response parameter."""


class PJLinkPassword(PJLinkException):
    """Invalid or absent password."""


class PJLinkProjectorError(PJLinkException):
    """Projector raised an error when handling a command."""


class PJLinkERR1(PJLinkProtocolError):
    """ERR 1, undefined command, as specified in (§2.2)"""


class PJLinkERR2(PJLinkException):
    """ERR 2, out of parameter, as specified in (§2.2)"""


class PJLinkERR3(PJLinkException):
    """ERR 3, unavailable at the current time or in the current projector state, as specified in (§2.2)"""


class PJLinkERR4(PJLinkException):
    """ERR 4, projector or display failure, as specified in (§2.2)"""
