# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import pytest

from server.config import MAX_QUANTITY
from server.deck_import import DeckLine, parse_deck_list, resolve_deck_lines, split_name_version
from server.errors import CardNotFoundError, InvalidResponseError, UpstreamUnavailableError
from server.models import ImportIssueReason, LorcastCard
from tests.conftest import named_card_payload


def make_card(name: str, version: str | None, set_code: str = "10", number: str = "7") -> LorcastCard:
    return LorcastCard.model_validate(named_card_payload(name, version, set_code, number))


class FakeLorcast:
    """Stands in for LorcastClient.search_card; maps (name, version) to a card or an exception."""

    def __init__(self, results: dict[tuple[str, str | None], LorcastCard | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[str, str | None]] = []

    async def search_card(self, name: str, version: str | None) -> LorcastCard:
        self.calls.append((name, version))
        result = self.results[(name, version)]
        if isinstance(result, Exception):
            raise result
        return result


def test_parses_dreamborn_lines() -> None:
    parsed = parse_deck_list("4 Hercules - Spectral Demigod\n2 Bunch of Balloons\n")
    assert parsed.issues == []
    assert [(line.quantity, line.name, line.version) for line in parsed.lines] == [
        (4, "Hercules", "Spectral Demigod"),
        (2, "Bunch of Balloons", None),
    ]


@pytest.mark.parametrize("line", ["4x Hercules - Spectral Demigod", "4 x Hercules - Spectral Demigod", "4X Hercules - Spectral Demigod"])
def test_accepts_x_after_count(line: str) -> None:
    parsed = parse_deck_list(line)
    assert [(line.quantity, line.name) for line in parsed.lines] == [(4, "Hercules")]


def test_blank_lines_are_skipped_but_line_numbers_are_kept() -> None:
    parsed = parse_deck_list("\n\n   \n1 Dragon Fire\nnonsense")
    assert parsed.lines[0].line_number == 4
    assert parsed.issues[0].line_number == 5


def test_normalizes_whitespace_and_curly_quotes() -> None:
    parsed = parse_deck_list("  3   Scrooge\u2019s   Counting House  -  Ebenezer\u2019s Office  ")
    line = parsed.lines[0]
    assert (line.name, line.version) == ("Scrooge's Counting House", "Ebenezer's Office")


def test_hyphen_inside_words_is_not_a_separator() -> None:
    assert split_name_version("Mulan - Quick-Tempered Warrior") == ("Mulan", "Quick-Tempered Warrior")
    assert split_name_version("Self-Named Item") == ("Self-Named Item", None)


def test_trailing_separator_means_no_version() -> None:
    assert split_name_version("Dragon Fire - ") == ("Dragon Fire", None)


@pytest.mark.parametrize("line", ["Hercules - Spectral Demigod", "four Hercules", "4", "4 ", "-1 Hercules"])
def test_malformed_lines_become_parse_errors(line: str) -> None:
    parsed = parse_deck_list(line)
    assert parsed.lines == []
    assert [issue.reason for issue in parsed.issues] == [ImportIssueReason.PARSE_ERROR]


def test_zero_count_is_invalid_quantity() -> None:
    parsed = parse_deck_list("0 Hercules - Spectral Demigod")
    assert parsed.lines == []
    assert parsed.issues[0].reason == ImportIssueReason.INVALID_QUANTITY


def test_duplicate_lines_merge_case_insensitively() -> None:
    parsed = parse_deck_list("2 Hercules - Spectral Demigod\n1 Dragon Fire\n2 hercules - spectral demigod")
    assert [(line.line_number, line.quantity) for line in parsed.lines] == [(1, 4), (2, 1)]


def test_merged_count_over_limit_is_reported() -> None:
    half = MAX_QUANTITY // 2 + 1
    parsed = parse_deck_list(f"{half} Dragon Fire\n{half} Dragon Fire")
    assert parsed.lines == []
    assert parsed.issues[0].reason == ImportIssueReason.INVALID_QUANTITY
    assert str(half * 2) in parsed.issues[0].detail


def test_single_line_over_limit_is_reported() -> None:
    parsed = parse_deck_list(f"{MAX_QUANTITY + 1} Dragon Fire")
    assert parsed.issues[0].reason == ImportIssueReason.INVALID_QUANTITY


def line(line_number: int, name: str, version: str | None, quantity: int = 1) -> DeckLine:
    return DeckLine(line_number, f"{quantity} {name}", quantity, name, version)


async def test_resolve_maps_cards_and_errors() -> None:
    fake = FakeLorcast(
        {
            ("Hercules", "Spectral Demigod"): make_card("Hercules", "Spectral Demigod", "11", "117"),
            ("Nope", None): CardNotFoundError("No card named 'Nope' on Lorcast"),
            ("Broken", None): InvalidResponseError("bad data"),
            ("Down", None): UpstreamUnavailableError("timed out"),
        }
    )
    lines = [line(1, "Hercules", "Spectral Demigod", 4), line(2, "Nope", None), line(3, "Broken", None), line(4, "Down", None)]
    cards, issues = await resolve_deck_lines(fake, lines)  # type: ignore[arg-type]

    assert [(card.set_code, card.number, card.quantity, card.name) for card in cards] == [
        ("11", "117", 4, "Hercules - Spectral Demigod")
    ]
    assert [(issue.line_number, issue.reason) for issue in issues] == [
        (2, ImportIssueReason.NOT_FOUND),
        (3, ImportIssueReason.INVALID_RESPONSE),
        (4, ImportIssueReason.UPSTREAM_UNAVAILABLE),
    ]
    assert fake.calls == [(item.name, item.version) for item in lines]


async def test_resolve_merges_lines_that_hit_the_same_printing() -> None:
    card = make_card("Dragon Fire", None, "10", "133")
    fake = FakeLorcast({("Dragon Fire", None): card, ("Dragon  Fire", None): card})
    cards, issues = await resolve_deck_lines(fake, [line(1, "Dragon Fire", None, 2), line(2, "Dragon  Fire", None, 1)])  # type: ignore[arg-type]
    assert issues == []
    assert [(card.number, card.quantity) for card in cards] == [("133", 3)]


async def test_unexpected_error_does_not_stop_other_lines() -> None:
    fake = FakeLorcast({("Boom", None): RuntimeError("bug"), ("Dragon Fire", None): make_card("Dragon Fire", None)})
    cards, issues = await resolve_deck_lines(fake, [line(1, "Boom", None), line(2, "Dragon Fire", None)])  # type: ignore[arg-type]
    assert len(cards) == 1
    assert issues[0].reason == ImportIssueReason.UPSTREAM_UNAVAILABLE
    assert "bug" not in issues[0].detail
