# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

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


_TYPOGRAPHIC_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
    }
)
_DOUBLE_QUOTE = '"'
_WHITESPACE_RUN = re.compile(r"\s+")
_SPACE = " "


def normalize_card_text(value: str) -> str:
    """Canonical form for card names typed or pasted by users.

    Curly quotes become straight, double quotes are removed (they can't appear inside a quoted Lorcast
    search term), and whitespace runs collapse to one space.
    """
    straightened = value.translate(_TYPOGRAPHIC_QUOTES).replace(_DOUBLE_QUOTE, "")
    return _WHITESPACE_RUN.sub(_SPACE, straightened).strip()


def card_name_key(name: str, version: str | None) -> tuple[str, str | None]:
    """Case- and punctuation-style-insensitive key for comparing card names."""
    normalized_version = normalize_card_text(version).casefold() if version else None
    return normalize_card_text(name).casefold(), normalized_version or None
