"""_debug.py

Shared logging helpers for projector traffic debugging.
"""

import logging

LOGGER = logging.getLogger("aiopjlink")


def redact_debug_payload(payload: str) -> str:
    """Redact PJLink authentication data before logging."""
    if payload.upper().startswith(("PJLINK 1 ", "PJLINK 2 ")):
        return f"{payload[:9]}<redacted>"
    return payload
