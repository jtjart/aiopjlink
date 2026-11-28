"""Shared logging helpers for projector traffic debugging."""

import logging

LOGGER = logging.getLogger("aiopjlink2")


def redact_debug_payload(payload: str) -> str:
    """Redact PJLink authentication data before logging.

    A welcome line (`PJLINK 1 <token>`) or a security reply (`PJLINK 2 <random number>`) carries the random number
    a password digest is built from, so everything after its prefix is replaced.

    Returns:
        The original payload or a redacted version of a PJLink authentication greeting or reply.
    """
    if payload.upper().startswith(("PJLINK 1 ", "PJLINK 2 ")):
        return f"{payload[:9]}<redacted>"
    return payload
