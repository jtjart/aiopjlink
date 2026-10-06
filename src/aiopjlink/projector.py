"""projector.py

The `PJLink` class is a connection to a projector using the PJLink protocol.

To provide a "pythonic" API for the different PJLink commands, the
class `CommandGroup` is overriden and groups together related commands.

No state is kept inside the classes (apart from the lock that serialises
the commands sent through one `PJLink` object).

Error handling
--------------
See `aiopjlink.exceptions`: everything raised here is a subclass of `PJLinkException`.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from enum import Enum

from ._transport import Transport
from .commands.base import CommandGroup
from .commands.power import Power
from .enums import PJClass
from .exceptions import (
    PJLinkERR1,
    PJLinkERR2,
    PJLinkProjectorError,
    PJLinkUnexpectedResponseParameter,
)


class PJLink(Transport):
    """Manages a PJLink connection to a projector.

    Every command opens its own short-lived connection, so there is nothing to
    open or close. One object can safely be shared between several tasks:
    commands are sent one after the other.

    Usage:

        >>> link = PJLink(address='192.168.100.100', password='secret')
        >>> await link.power.turn_off()
        >>> await asyncio.sleep(4)
        >>> await link.power.turn_on()

    """

    C1 = PJClass.ONE
    C2 = PJClass.TWO

    def __init__(
        self,
        address: str,
        port: int = 4352,
        password: str | None = None,
        timeout: float = 4,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(address, port, password, timeout, encoding)

        # One command at a time: many projectors only accept a single connection.
        self._lock = asyncio.Lock()

        # Add the different API namespaces.
        self.info: Information = Information(self)
        self.power: Power = Power(self)
        self.sources: Sources = Sources(self)
        self.mute: Mute = Mute(self)
        self.errors: Errors = Errors(self)
        self.lamps: Lamp = Lamp(self)
        self.filter: Filter = Filter(self)
        self.freeze: Freeze = Freeze(self)
        self.microphone: Volume = Volume(self, "MVOL")
        self.speaker: Volume = Volume(self, "SVOL")

    async def wait_for_notification(self) -> None:
        raise NotImplementedError("class 2 method not supported")


class Sources(CommandGroup):
    """Control and query projector input sources."""

    class Mode(Enum):
        """Display input source modes (§4.3)."""

        RGB = "1"
        VIDEO = "2"
        DIGITAL = "3"
        STORAGE = "4"
        NETWORK = "5"
        INTERNAL = "6"
        """ Class 2 only. """

    async def set(self, mode: Mode, index: str | int, pjclass: PJClass = PJClass.ONE) -> None:
        """Set the current source input selection (§4.3)."""
        return await self._transmit_ok(command="INPT", param=f"{mode.value}{self._check_index(index)}", pjclass=pjclass)

    async def get(self, pjclass: PJClass = PJClass.ONE) -> tuple[Mode, str]:
        """Get the current source input selection (§4.4)."""
        values = await self._link.transmit(command="INPT", param="?", pjclass=pjclass)
        if len(values) != 2:
            raise PJLinkUnexpectedResponseParameter("expected 2 INPT response characters")
        try:
            return Sources.Mode(values[0]), values[1]
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected input source mode") from err

    _INDEX_CHARS = '123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    @staticmethod
    def _check_index(index: int | str) -> str:
        """Return the single character the protocol uses for an input index (1-9, A-Z).

        An int maps onto that alphabet (11 is "B"). A string must already be a single
        character, so "11" is rejected. Lower case is accepted.
        """
        chars = Sources._INDEX_CHARS
        if isinstance(index, int):
            if 1 <= index <= len(chars):
                return chars[index - 1]
            raise ValueError(f'index must be between 1 and {len(chars)}')
        if len(index) == 1 and index.isascii() and index.upper() in chars:
            return index.upper()
        raise ValueError('index must be a single character (1-9 for Class 1, and 1-9A-Z for Class 2)')

    async def available(self, pjclass: PJClass = PJClass.ONE) -> list[tuple[Mode, str]]:
        """List all the available input sources (§4.9).

        Returns:
            A list of available input sources in the format: (Sources.Mode, index str).  For example:
                [(<Mode.RGB: '1'>, '1'), (<Mode.DIGITAL: '3'>, '1'), ...]
        """
        response = await self._link.transmit("INST", "?", pjclass)
        try:
            sources = response.split()
            if not sources or any(len(source) != 2 for source in sources):
                raise ValueError("invalid source format")
            return [(Sources.Mode(source[0]), source[1]) for source in sources]
        except (ValueError, IndexError) as err:
            raise PJLinkUnexpectedResponseParameter("unable to parse available sources") from err

    async def get_source_name(self, mode: Mode, index: str | int) -> str:
        """Get the name of a given input source (§4.17).
        :param mode Sources.Mode: The input mode to select.
        :param index str: A single character.
        """
        return await self._link.transmit(
            command="INNM", param=f"?{mode.value}{self._check_index(index)}", pjclass=PJClass.TWO
        )

    async def available_with_names(self) -> list[tuple[Mode, str, str | None]]:
        """List all the available input sources with names (§4.17).
        Returns:
            A list of available input sources in the format (Source.Mode, index str, name str).
            For example:
                [(<Mode.RGB: '1'>, '1', 'Computer'), (<Mode.DIGITAL: '3'>, '1', 'DVI-D'), ...]
        """
        sources = await self.available(pjclass=PJClass.TWO)
        output = []
        for mode, index in sources:
            try:
                name = await self.get_source_name(mode, index)
            except PJLinkERR2:
                name = None
            output.append((mode, index, name))
        return output

    async def resolution(self) -> tuple[int, ...]:
        """Get the current projector resolution (§4.18)
        Returns:
            (x:int, y:int) tuple: Horizontal and vertical resolutions of input signal respectively.
        """
        response = await self._link.transmit("IRES", "?", PJClass.TWO)
        if response == "-":
            raise PJLinkProjectorError("no signal input")
        if response == "*":
            raise PJLinkProjectorError("unknown signal")

        # Convert each axis to an integer.
        try:
            resolution = [int(dim) for dim in re.split("x", response, flags=re.IGNORECASE)]
            return tuple(resolution)
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unable to parse resolution") from err

    async def recommended_resolution(self) -> tuple[int, ...]:
        """Get the current recommended resolution (§4.19)
        Returns:
            (x, y) tuple: Horizontal and vertical resolutions of input signal respectively.
        """
        response = await self._link.transmit("RRES", "?", PJClass.TWO)
        try:
            resolution = [int(dim) for dim in re.split("x", response, flags=re.IGNORECASE)]
            return tuple(resolution)
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unable to parse resolution") from err


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


class Errors(CommandGroup):
    """Provide information about errors occuring within the projector (§4.7)."""

    class Category(Enum):
        """The different types of error returned according to (§4.7)."""

        FAN = "fan"
        LAMP = "lamp"
        TEMP = "temperature"
        COVER = "cover"
        FILTER = "filter"
        OTHER = "other"

    class Level(Enum):
        """Error level for each `Category` (§4.7)."""

        OK = "0"
        WARN = "1"
        ERROR = "2"

    async def query(self) -> dict[Category, Level]:
        """Query the projecteor for the latest error status
        information for each of the error categories (§4.7).

        Returns:
            dict[Category]: Level: Table of error categories to states.
        """
        errors = await self._link.transmit("ERST", "?", pjclass=PJClass.ONE)
        if len(errors) != 6:
            raise PJLinkUnexpectedResponseParameter("unexpected number of error types reported")
        try:
            return {
                Errors.Category.FAN: Errors.Level(errors[0]),
                Errors.Category.LAMP: Errors.Level(errors[1]),
                Errors.Category.TEMP: Errors.Level(errors[2]),
                Errors.Category.COVER: Errors.Level(errors[3]),
                Errors.Category.FILTER: Errors.Level(errors[4]),
                Errors.Category.OTHER: Errors.Level(errors[5]),
            }
        except IndexError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected number of error types reported") from err
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unknown error level") from err


class Lamp(CommandGroup):
    """Status information about the projector light sources (§4.8).

    According to the spec the "usage time of lamp is always 0 when it is
    not counted by the projector."
    """

    class State(Enum):
        OFF = "0"
        ON = "1"

    async def status(self) -> list[tuple[int, State]]:
        """Query the current lamp hours and lamp statuses.
        There may be more than one lamp in some projectors, so this is returned
        as a list.
        Returns:
            [(hours:int, state:Lamp.State)]: List of lamp hours and states for each lamp.
        """
        # Express a special meaning for ERR1 (§4.8).
        try:
            response = await self._link.transmit("LAMP", "?", pjclass=PJClass.ONE)
        except PJLinkERR1 as err:
            raise PJLinkERR1("no lamp") from err

        # Split the response by " " and then pair up all the numbers from
        # the list in groups of 2.  If there are any remainders, raise an error.
        # See: https://docs.python.org/3/library/itertools.html (grouper)
        # This takes a line like: "1000 1 50 0" and breaks it into pairs:
        #   (1000, 1), (50, 0)
        # Such that these can then be remapped into our high level interface.
        try:
            # Python 3.9 solution.
            pairs = []
            numbers = response.split(" ")
            for i in range(0, len(numbers), 2):
                pairs.append(numbers[i : i + 2])

            # Python 3.10 solution.
            # pairs = zip(*[iter(response.split(' '))] * 2, strict=True)
            # pairs = [pair for pair in pairs]#

            # Remap the statuses to integers and our lamp state enum.
            return [(int(hours), Lamp.State(state)) for hours, state in pairs]
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unparsable lamp status") from err

    async def hours(self) -> int:
        """How long has the first lamp been on (hour, integer).

        According to the spec (§4.8) the "usage time of lamp is always 0 when it is
        not counted by the projector."
        """
        return (await self.status())[0][0]

    async def replacement_models(self) -> list[str]:
        """Get the lamp replacement models listed in the projector.
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._link.transmit("RLMP", "?", pjclass=PJClass.TWO)
        return [m for m in models.split(" ") if m]


class Filter(CommandGroup):
    """Status information about the projector filters (§4.20, §4.22)."""

    async def hours(self) -> int:
        """Query the filter usage time (§4.20).
        Filter usage time is always 0 when it is not counted by the projector.
        """
        # Request the value.
        try:
            return int(await self._link.transmit("FILT", "?", pjclass=PJClass.TWO))

        # Express a special meaning for ERR1 (§4.20).
        except PJLinkERR1 as err:
            raise PJLinkERR1("no filter") from err

        # Parse issue.
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("filter usage not parsable") from err

    async def replacement_models(self) -> list[str]:
        """Get the filter replacement models listed in the projector (§4.22).
        There may be more than one model number, so they are returned in a list.
        """
        models = await self._link.transmit("RFIL", "?", pjclass=PJClass.TWO)
        return [m for m in models.split(" ") if m]


class Freeze(CommandGroup):
    """Controls freezing and unfreezing the current frame (§4.25, §4.26)."""

    async def set(self, freeze: bool) -> None:
        """Freeze or unfreeze the screen (§4.25)."""
        cmd = "1" if bool(freeze) else "0"
        await self._transmit_ok("FREZ", cmd, pjclass=PJClass.TWO)

    async def get(self) -> bool:
        """Returns True if the screen is currently frozen, and False if not §4.26."""
        response = await self._link.transmit("FREZ", "?", pjclass=PJClass.TWO)
        if response == "0":
            return False
        if response == "1":
            return True
        raise PJLinkUnexpectedResponseParameter("unexpected freeze state")


class Volume(CommandGroup):
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

    def __init__(self, link: PJLink, instruction: str) -> None:
        super().__init__(link)
        self.instruction = instruction

    async def turn_up(self) -> None:
        """Increase the volume by one unit."""
        await self._transmit_ok(self.instruction, "1", pjclass=PJClass.TWO)

    async def turn_down(self) -> None:
        """Decrease the volume by one unit."""
        await self._transmit_ok(self.instruction, "0", pjclass=PJClass.TWO)


class Information(CommandGroup):
    """Gathers information about the projector."""

    async def table(self) -> dict[str, str | None]:
        """Collect a table of all the different information available
        from this projector.  If the projector responds, an empty string is
        returned, but if it throws an error, `None` is returned.

        See the code for the dictionary entries.
        """

        # Helper to ensure it is always returned regardless of the exception.
        async def _safe(method: Callable[[], Awaitable[str | PJClass]]) -> str | None:
            try:
                return str(await method())
            except Exception:
                return None

        # Table.
        return {
            "software_version": await _safe(self.software_version),
            "serial_number": await _safe(self.serial_number),
            "pjlink_class": await _safe(self.pjlink_class),
            "other": await _safe(self.other),
            "product_name": await _safe(self.product_name),
            "manufacturer_name": await _safe(self.manufacturer_name),
            "projector_name": await _safe(self.projector_name),
        }

    async def software_version(self) -> str:
        """Request software version of the projector (§4.16).
        The version information of the software defined by the manufacturer is indicated.
        Version information can be expressed in any way.

        Returns:
            str: The version string.
        """
        return await self._link.transmit("SVER", "?", PJClass.TWO)

    async def serial_number(self) -> str:
        """Request the projector serial number (§4.15).
        The serial number information defined by the manufacturer is indicated.

        Returns:
            str: The serial number string.
        """
        return await self._link.transmit("SNUM", "?", PJClass.TWO)

    async def pjlink_class(self, pjclass: PJClass = PJClass.ONE) -> PJClass:
        """Get projectors PJLink class number as a `PJClass` enumeration (§4.14)"""
        try:
            return PJClass(await self._link.transmit("CLSS", "?", pjclass=pjclass))
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unexpected PJLink class") from err

    async def other(self) -> str:
        """Query the projector for other information about the projector/display
        described by the manufacture. Defined as in (§4.13).

        If there is no other information, this returns an empty string.
        """
        return await self._link.transmit("INFO", "?", PJClass.ONE)

    async def product_name(self) -> str:
        """Get product name information string (e.g. EPSON PU1007B/PU1007W) as in (§4.12).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("INF2", "?", PJClass.ONE)

    async def manufacturer_name(self) -> str:
        """Get manufacturer name information string (e.g. EPSON) as in (§4.11).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("INF1", "?", PJClass.ONE)

    async def projector_name(self) -> str:
        """Get projector name information string (e.g. EBB13648) as in (§4.10).

        If there is no information, this returns an empty string.
        """
        return await self._link.transmit("NAME", "?", PJClass.ONE)
