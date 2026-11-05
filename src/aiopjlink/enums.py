"""enums.py

Enumerations shared by the whole library.

Enumerations that belong to a single command group (e.g. `Power.State`,
`Sources.Mode`) live next to that group in `aiopjlink.commands`.
"""

from enum import Enum


class PJClass(Enum):
    """Communication protocol message version.

    Class 1 is the most common type of PJLink, and is used for basic commands such as
    power on/off, input selection, and adjusting volume.

    Class 2 is an extended version of the protocol that supports additional commands such
    as opening and closing the projector's lens cover, and is typically used by more sophisticated devices.
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
    """ SHA256 only: a projector that does not support it is an error (`PJLinkNotSupported`), never a downgrade. """

    MD5 = "md5"
    """ MD5 only: `PJLINK 2` is never sent. For projectors that cannot cope with the question. """
