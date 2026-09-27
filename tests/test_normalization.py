# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import pytest

from server.normalization import normalize_identifier, set_code_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("010", "10"),
        ("007", "7"),
        ("0", "0"),
        ("000", "0"),
        ("P1", "P1"),
        ("  12  ", "12"),
        ("cp", "cp"),
        ("0A", "0A"),
        ("", ""),
    ],
)
def test_normalize_identifier(raw: str, expected: str) -> None:
    assert normalize_identifier(raw) == expected


def test_set_code_key_is_case_insensitive() -> None:
    assert set_code_key("p1") == set_code_key("P1")
