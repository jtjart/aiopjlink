"""Enumerations shared by the whole library.

Enumerations that belong to a single command group (e.g. `Power.State`,
`Sources.Mode`) live next to that group in `aiopjlink2.commands`.
"""

from enum import Enum


class PJClass(Enum):
    """The PJLink class a command line belongs to: the digit after the `%` (§2.1).

    Class 1 performs the basic control of a projector: power, input selection, mute, error and lamp status,
    and information queries. Class 2 adds commands (input names and resolutions, filters, speaker and microphone
    volume, freeze, serial number, software version) as well as the device search and the status notifications.
    Use `PJClass.TWO` for Class 2-only commands; `PJClass.ONE` is the default.
    """

    ONE = "1"
    """ PJLink Class 1 command. """

    TWO = "2"
    """ PJLink Class 2 command. """


class PJAuth(Enum):
    """Which password authentication to use with a projector that has security switched on (§5).

    The original PJLink authenticates with MD5. Specification 2.10 added SHA256, which a controller
    asks for after the projector's greeting (`PJLINK 2`). A projector that does not know the question
    answers it in one of several ways, or not at all, and the spec then has the controller reconnect with MD5.
    """

    AUTO = "auto"
    """ Ask for SHA256; if the projector does not support it, reconnect and use MD5 (the spec's procedure).
    The outcome is remembered, so only the first connection to an MD5 projector pays for the question. If MD5 is
    rejected later by a projector that never said it lacks SHA256, the command asks again, for SHA256 only. """

    SHA256 = "sha256"
    """SHA256 only: a projector that does not support it is an error (`PJLinkNotSupportedError`), never a downgrade."""

    MD5 = "md5"
    """MD5 only: `PJLINK 2` is never sent. For projectors that cannot cope with the question."""
