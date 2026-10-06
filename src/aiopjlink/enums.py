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
