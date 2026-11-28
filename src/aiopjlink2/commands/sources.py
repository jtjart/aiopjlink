"""Input source selection and information (§4.3, §4.4, §4.9, §4.17 - §4.19).

Commands: `INPT`, `INPT ?`, `INST ?`, `INNM ?`, `IRES ?` and `RRES ?`.
"""

import re
from enum import Enum

from ..enums import PJClass
from ..exceptions import (
    PJLinkInvalidParameterError,
    PJLinkProjectorError,
    PJLinkUnexpectedValueError,
)
from ._sender import CommandSender

_RESOLUTION_PATTERN = re.compile(r"([0-9]+)x([0-9]+)", re.IGNORECASE)

_UNPARSABLE_SOURCES = "unable to parse available sources"
_SOURCE_TOKEN_LENGTH = 2


def _parse_resolution(resolution_text: str) -> tuple[int, int]:
    """Parse `<width>x<height>` (§4.18, §4.19) into `(width, height)`.

    Returns:
        The horizontal and vertical resolution.

    Raises:
        PJLinkUnexpectedValueError: The resolution text is not in `<width>x<height>` format.
    """
    resolution_match = _RESOLUTION_PATTERN.fullmatch(resolution_text)
    if resolution_match is None:
        raise PJLinkUnexpectedValueError(f"unable to parse resolution: {resolution_text}")
    return int(resolution_match[1]), int(resolution_match[2])


class Sources:
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

    def __init__(self, sender: CommandSender) -> None:
        """Initialize the input source command handler."""
        self._sender = sender

    async def set(self, mode: Mode, index: str | int, pjclass: PJClass = PJClass.ONE) -> None:
        """Set the current source input selection (§4.3).

        Args:
            mode: The kind of input.
            index: 1-9 for both Class 1 and Class 2 projectors, and A-Z for a Class 2 projector. An int is mapped
                onto that alphabet (11 is "B").
            pjclass: The class of the command line (`PJClass.TWO` for the indexes A-Z).

        Raises:
            ValueError: `index` is not a valid input index. Nothing is sent.
        """
        await self._sender.transmit_expecting_ok(
            command="INPT", parameter=f"{mode.value}{self._to_index_character(index)}", pjclass=pjclass
        )

    async def get(self, pjclass: PJClass = PJClass.ONE) -> tuple[Mode, str]:
        """Get the current source input selection (§4.4).

        Returns:
            The selected source mode and input index.

        Raises:
            PJLinkUnexpectedValueError: The response contains an invalid source mode.
        """
        return parse_input_source(await self._sender.query_status("INPT", pjclass))

    _INDEX_CHARACTERS = '123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    """The input indexes of the protocol, in the order integers map onto them: 1 is "1", 10 is "A"."""

    @staticmethod
    def _to_index_character(index: int | str) -> str:
        """Return the single character the protocol uses for an input index (1-9, A-Z).

        Integer indexes map onto the sequence 1-9, A-Z (10 is "A"); strings must be a single
        character from that sequence. Lower case is accepted.

        Returns:
            The protocol character for the input index.

        Raises:
            ValueError: The index is outside 1-9A-Z or is not a single character.
        """
        valid_characters = Sources._INDEX_CHARACTERS
        if isinstance(index, int):
            if 1 <= index <= len(valid_characters):
                return valid_characters[index - 1]
            raise ValueError(f'index must be between 1 and {len(valid_characters)}')
        if len(index) == 1 and index.isascii() and index.upper() in valid_characters:
            return index.upper()
        raise ValueError('index must be a single character (1-9 for Class 1, and 1-9A-Z for Class 2)')

    async def available(self, pjclass: PJClass = PJClass.ONE) -> list[tuple[Mode, str]]:
        """List all the available input sources (§4.9).

        Returns:
            A list of available input sources in the format: (Sources.Mode, index str).  For example:
                [(<Mode.RGB: '1'>, '1'), (<Mode.DIGITAL: '3'>, '1'), ...]

        Raises:
            PJLinkUnexpectedValueError: The source list is malformed or contains an unknown mode.
        """
        source_tokens = (await self._sender.query_status("INST", pjclass)).split()
        if not source_tokens or any(len(source_token) != _SOURCE_TOKEN_LENGTH for source_token in source_tokens):
            raise PJLinkUnexpectedValueError(_UNPARSABLE_SOURCES)
        try:
            return [
                (Sources.Mode(source_token[0]), Sources._to_index_character(source_token[1]))
                for source_token in source_tokens
            ]
        except ValueError as err:
            raise PJLinkUnexpectedValueError(_UNPARSABLE_SOURCES) from err

    async def get_source_name(self, mode: Mode, index: str | int) -> str:
        """Get the name of an input source (§4.17).

        Args:
            mode: The kind of input.
            index: The input index, as for `set`.

        Returns:
            The projector's name for the selected input source.

        Raises:
            ValueError: `index` is not a valid input index. Nothing is sent.
        """
        return await self._sender.transmit("INNM", f"?{mode.value}{self._to_index_character(index)}", PJClass.TWO)

    async def available_with_names(self) -> list[tuple[Mode, str, str | None]]:
        """List all the available input sources with their names (§4.17).

        Returns:
            Each source as a ``(mode, index, name)`` tuple. The name is None if the projector answers ERR2.
        """
        available_sources = await self.available(pjclass=PJClass.TWO)
        return [(mode, index, await self._source_name_or_none(mode, index)) for mode, index in available_sources]

    async def _source_name_or_none(self, mode: Mode, index: str) -> str | None:
        """Get the name of an input, treating ERR2 as no name.

        Returns:
            The source name, or None if the projector answers ERR2.
        """
        try:
            return await self.get_source_name(mode, index)
        except PJLinkInvalidParameterError:
            return None

    async def resolution(self) -> tuple[int, int]:
        """Get the resolution of the current input signal (§4.18).

        Returns:
            The horizontal and vertical resolution, in that order.

        Raises:
            PJLinkProjectorError: There is no signal input, or the signal is unknown (the projector answers `-`
                or `*`).
            PJLinkUnexpectedValueError: The resolution response is malformed.
        """
        response_parameter = await self._sender.query_status("IRES", PJClass.TWO)
        if response_parameter == "-":
            raise PJLinkProjectorError("no signal input")
        if response_parameter == "*":
            raise PJLinkProjectorError("unknown signal")
        return _parse_resolution(response_parameter)

    async def recommended_resolution(self) -> tuple[int, int]:
        """Get the recommended resolution of the current input (§4.19).

        Returns:
            The horizontal and vertical resolution, in that order.

        Raises:
            PJLinkUnexpectedValueError: The resolution response is malformed.
        """
        return _parse_resolution(await self._sender.query_status("RRES", PJClass.TWO))


def parse_input_source(input_parameter: str) -> tuple[Sources.Mode, str]:
    """Parse `<mode><index>` of an `INPT` query response (§4.4) or status notification (§3.3.2).

    Returns:
        The parsed source mode and input index.

    Raises:
        PJLinkUnexpectedValueError: The input parameter is malformed or uses an unknown mode.
    """
    if len(input_parameter) != _SOURCE_TOKEN_LENGTH:
        raise PJLinkUnexpectedValueError(f"expected {_SOURCE_TOKEN_LENGTH} INPT response characters")
    try:
        return Sources.Mode(input_parameter[0]), input_parameter[1]
    except ValueError as err:
        raise PJLinkUnexpectedValueError("unexpected input source mode") from err
