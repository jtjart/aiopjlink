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
from .base import CommandGroup


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
        values = await self._transmit_state("INPT", pjclass)
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
        response = await self._transmit_state("INST", pjclass)
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
            except PJLinkInvalidParameter:
                name = None
            output.append((mode, index, name))
        return output

    async def resolution(self) -> tuple[int, ...]:
        """Get the current projector resolution (§4.18)
        Returns:
            (x:int, y:int) tuple: Horizontal and vertical resolutions of input signal respectively.
        """
        response = await self._transmit_state("IRES", PJClass.TWO)
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
        response = await self._transmit_state("RRES", PJClass.TWO)
        try:
            resolution = [int(dim) for dim in re.split("x", response, flags=re.IGNORECASE)]
            return tuple(resolution)
        except ValueError as err:
            raise PJLinkUnexpectedResponseParameter("unable to parse resolution") from err
