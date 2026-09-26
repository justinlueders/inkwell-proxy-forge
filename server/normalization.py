"""Normalization of user-entered set codes and card numbers to the form Lorcast expects."""

import re

_ASCII_DIGITS = re.compile(r"[0-9]+")
_ZERO = "0"


def normalize_identifier(value: str) -> str:
    """Trim whitespace and strip leading zeros from purely numeric values.

    Lorcast returns 404 for "010" or "007"; it expects "10" and "7".
    """
    trimmed = value.strip()
    if _ASCII_DIGITS.fullmatch(trimmed):
        return trimmed.lstrip(_ZERO) or _ZERO
    return trimmed


def set_code_key(set_code: str) -> str:
    """Case-insensitive key for matching set codes (Lorcast codes are case-sensitive)."""
    return set_code.casefold()
