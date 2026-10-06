"""commands/mute.py

Audio and video mute (§4.5 AVMT, §4.6 AVMT ?).
"""

from ..enums import PJClass
from ..exceptions import PJLinkUnexpectedResponseParameter
from .base import CommandGroup


class Mute(CommandGroup):
    """Control audio and visual track mute status (§4.5, §4.6).

    If the mute function is individually executed or cancelled for the models
    that do not have audio or video mute functions, "ERR 2" (out of parameter range) is returned.
    """

    async def status(self) -> tuple[bool, bool]:
        """Current (video, audio) track mute status returned as two booleans (§4.6).

        Returns:
            tuple(video: bool, audio: bool): True if the track is muted.  False if not.
        """
        status = await self._link.transmit("AVMT", "?", pjclass=PJClass.ONE)
        if status == "11":
            return True, False
        if status == "21":
            return False, True
        if status == "31":
            return True, True
        if status == "30":
            return False, False
        raise PJLinkUnexpectedResponseParameter("unexpected mute response")

    async def video(self, muted: bool) -> None:
        """Set if the video track should be muted (True to mute, False to unmute)."""
        cmd = "1" if muted is True else "0"
        await self._transmit_ok("AVMT", f"1{cmd}", pjclass=PJClass.ONE)

    async def audio(self, muted: bool) -> None:
        """Set if the audio track should be muted (True to mute, False to unmute)."""
        cmd = "1" if muted is True else "0"
        await self._transmit_ok("AVMT", f"2{cmd}", pjclass=PJClass.ONE)

    async def both(self, muted: bool) -> None:
        """Set if the AV tracks should be muted (True to mute, False to unmute)."""
        cmd = "1" if muted is True else "0"
        await self._transmit_ok("AVMT", f"3{cmd}", pjclass=PJClass.ONE)

    async def set(self, video: bool | None, audio: bool | None) -> None:
        """Enable or disable mute for each track (call mirrors output of `status`).
        :param video (bool): True to mute. False to unmute. None to skip.
        :param audio (bool): True to mute. False to unmutes. None to skip.
        """
        # Skip non-specified condition.
        if video is None and audio is None:
            return

        # Fully specified conditions.
        if video is True and audio is True:
            await self.both(True)
        elif video is False and audio is False:
            await self.both(False)

        # Partially specified conditions.
        else:
            if video is not None:
                await self.video(video)
            if audio is not None:
                await self.audio(audio)
