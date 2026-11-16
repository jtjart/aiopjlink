"""commands/volume.py

Speaker and microphone volume (§4.23 SVOL, §4.24 MVOL).
"""

from ..enums import PJClass
from ._sender import CommandSender

_NOT_INSTALLED_MESSAGES = {"SVOL": "no speaker installed", "MVOL": "no microphone installed"}


class Volume:
    """Controls a xVOL style command (e.g. for speakers and microphones) as
    defined in (§4.23, §4.24).

    According to the spec:
        "As for a specification to increase the microphone volume by one level when it
        is in the maximum state, and a specification to decrease the microphone
        volume by one level when it is in the minimum state, the response
        for a normal case is returned."

    Volume related to audio output (audio out, built-in speaker in equipment
    model, etc.) is referred to as the speaker volume.

    Volume related to voice input (audio in, microphone terminal to be input
    to the model, etc.) is referred to as the microphone volume.
    """

    def __init__(self, sender: CommandSender, command: str) -> None:
        self._sender = sender
        self.command = command
        # ERR1 means the device is not installed (§4.23, §4.24).
        self._not_installed_message = _NOT_INSTALLED_MESSAGES.get(command)

    async def turn_up(self) -> None:
        """Increase the volume by one unit."""
        await self._sender.transmit_expecting_ok(
            self.command, "1", PJClass.TWO, not_supported_message=self._not_installed_message
        )

    async def turn_down(self) -> None:
        """Decrease the volume by one unit."""
        await self._sender.transmit_expecting_ok(
            self.command, "0", PJClass.TWO, not_supported_message=self._not_installed_message
        )
