"""Groups of related PJLink commands, one module per feature (power, sources, mute, ...)."""

from .base import CommandGroup
from .power import Power

__all__ = ["CommandGroup", "Power"]
