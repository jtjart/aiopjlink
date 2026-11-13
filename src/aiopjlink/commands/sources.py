"""commands/sources.py

Input source selection and information (§4.3 INPT, §4.4 INPT ?, §4.9 INST ?,
§4.17 INNM ?, §4.18 IRES ?, §4.19 RRES ?).
"""

import re
from enum import Enum

from ..enums import PJClass
from ..exceptions import (
    PJLinkInvalidParameter,
    PJLinkProjectorError,
    PJLinkUnexpectedResponseParameter,
)
from ._sender import CommandSender

_RESOLUTION_PATTERN = re.compile(r"([0-9]+)x([0-9]+)", re.IGNORECASE)

_UNPARSABLE_SOURCES = "unable to parse available sources"
_SOURCE_TOKEN_LENGTH = 2


def _parse_resolution(resolution_text: str) -> tuple[int, int]:
    """Parse `<width>x<height>` (§4.18, §4.19) into `(width, height)`."""
    resolution_match = _RESOLUTION_PATTERN.fullmatch(resolution_text)
    if resolution_match is None:
        raise PJLinkUnexpectedResponseParameter(f"unable to parse resolution: {resolution_text}")
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
        self._sender = sender

    async def set(self, mode: Mode, index: str | int, pjclass: PJClass = PJClass.ONE) -> None:
        """Set the current source input selection (§4.3).

        `mode` is a `Sources.Mode`
        `index` is 1-9 for both Class 1 and Class 2 projectors, and A-Z (or the integer 10-35) for a Class 2 projector.
        """
        await self._sender.transmit_expecting_ok(
            command="INPT", parameter=f"{mode.value}{self._to_index_character(index)}", pjclass=pjclass
        )

    async def get(self, pjclass: PJClass = PJClass.ONE) -> tuple[Mode, str]:
        """Get the current source input selection (§4.4)."""
        return parse_input_source(await self._sender.query_status("INPT", pjclass))

    _INDEX_CHARACTERS = '123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    @staticmethod
    def _to_index_character(index: int | str) -> str:
        """Return the single character the protocol uses for an input index (1-9, A-Z).

        An int maps onto that alphabet (11 is "B"). A string must already be a single
        character, so "11" is rejected. Lower case is accepted.
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
        """
        source_tokens = (await self._sender.query_status("INST", pjclass)).split()
        if not source_tokens or any(len(source_token) != _SOURCE_TOKEN_LENGTH for source_token in source_tokens):
            raise PJLinkUnexpectedResponseParameter(_UNPARSABLE_SOURCES)
        try:
            return [(Sources.Mode(source_token[0]), source_token[1]) for source_token in source_tokens]
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter(_UNPARSABLE_SOURCES) from err

    async def get_source_name(self, mode: Mode, index: str | int) -> str:
        """Get the name of a given input source (§4.17).
        :param mode Sources.Mode: The input mode to select.
        :param index str: A single character.
        """
        return await self._sender.transmit("INNM", f"?{mode.value}{self._to_index_character(index)}", PJClass.TWO)

    async def available_with_names(self) -> list[tuple[Mode, str, str | None]]:
        """List all the available input sources with names (§4.17).
        Returns:
            A list of available input sources in the format (Source.Mode, index str, name str).
            For example:
                [(<Mode.RGB: '1'>, '1', 'Computer'), (<Mode.DIGITAL: '3'>, '1', 'DVI-D'), ...]
        """
        available_sources = await self.available(pjclass=PJClass.TWO)
        return [(mode, index, await self._source_name_or_none(mode, index)) for mode, index in available_sources]

    async def _source_name_or_none(self, mode: Mode, index: str) -> str | None:
        """The name of an input, or None if the projector has no name for it (`ERR2`)."""
        try:
            return await self.get_source_name(mode, index)
        except PJLinkInvalidParameter:
            return None

    async def resolution(self) -> tuple[int, int]:
        """Get the current projector resolution (§4.18)
        Returns:
            (x:int, y:int) tuple: Horizontal and vertical resolutions of input signal respectively.
        """
        response_parameter = await self._sender.query_status("IRES", PJClass.TWO)
        if response_parameter == "-":
            raise PJLinkProjectorError("no signal input")
        if response_parameter == "*":
            raise PJLinkProjectorError("unknown signal")
        return _parse_resolution(response_parameter)

    async def recommended_resolution(self) -> tuple[int, int]:
        """Get the current recommended resolution (§4.19)
        Returns:
            (x:int, y:int) tuple: Horizontal and vertical resolutions of input signal respectively.
        """
        return _parse_resolution(await self._sender.query_status("RRES", PJClass.TWO))


def parse_input_source(input_parameter: str) -> tuple[Sources.Mode, str]:
    """Parse `<mode><index>` of an `INPT` query response (§4.4) or status notification (§3.3.2)."""
    if len(input_parameter) != _SOURCE_TOKEN_LENGTH:
        raise PJLinkUnexpectedResponseParameter(f"expected {_SOURCE_TOKEN_LENGTH} INPT response characters")
    try:
        return Sources.Mode(input_parameter[0]), input_parameter[1]
    except ValueError as err:
        raise PJLinkUnexpectedResponseParameter("unexpected input source mode") from err
