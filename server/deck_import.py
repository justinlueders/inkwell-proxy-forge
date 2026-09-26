"""Parse pasted deck lists (dreamborn.ink "count Name - Version" format) and resolve them to printings."""

import dataclasses
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from server.config import MAX_QUANTITY, MIN_QUANTITY, NAME_VERSION_SEPARATOR
from server.errors import LorcastError
from server.lorcast import LorcastClient
from server.models import CardErrorReason, ImportedCard, ImportIssue, ImportIssueReason
from server.normalization import card_name_key, normalize_card_text

logger = logging.getLogger(__name__)

IMPORT_LINE_PATTERN = re.compile(r"^(\d+)\s*[xX]?\s+(.+)$")
LINE_FORMAT_EXAMPLE = "4 Hercules - Spectral Demigod"

_CARD_ERROR_TO_IMPORT_REASON: dict[CardErrorReason, ImportIssueReason] = {
    CardErrorReason.NOT_FOUND: ImportIssueReason.NOT_FOUND,
    CardErrorReason.UNKNOWN_SET: ImportIssueReason.NOT_FOUND,
    CardErrorReason.INVALID_RESPONSE: ImportIssueReason.INVALID_RESPONSE,
}


@dataclass(frozen=True)
class DeckLine:
    line_number: int
    raw: str
    quantity: int
    name: str
    version: str | None

    @property
    def display_name(self) -> str:
        return f"{self.name}{NAME_VERSION_SEPARATOR}{self.version}" if self.version else self.name


@dataclass
class ParsedDeck:
    lines: list[DeckLine] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)


def split_name_version(text: str) -> tuple[str, str | None]:
    """Split on the first separator; hyphens inside words (e.g. "Quick-Tempered") are not separators."""
    name, separator, version = text.partition(NAME_VERSION_SEPARATOR)
    if not separator:
        return name.strip(), None
    return name.strip(), version.strip() or None


def _issue(line_number: int, line: str, reason: ImportIssueReason, detail: str) -> ImportIssue:
    return ImportIssue(line_number=line_number, line=line, reason=reason, detail=detail)


def parse_deck_list(text: str) -> ParsedDeck:
    """Parse deck list text. Every rejected line becomes an issue; nothing is dropped silently."""
    parsed = ParsedDeck()
    merged: dict[tuple[str, str | None], DeckLine] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = IMPORT_LINE_PATTERN.fullmatch(line)
        if match is None:
            parsed.issues.append(
                _issue(line_number, line, ImportIssueReason.PARSE_ERROR, f"Expected a line like '{LINE_FORMAT_EXAMPLE}'")
            )
            continue

        quantity = int(match.group(1))
        card_text = normalize_card_text(match.group(2))
        if quantity < MIN_QUANTITY:
            parsed.issues.append(
                _issue(line_number, line, ImportIssueReason.INVALID_QUANTITY, f"Count must be at least {MIN_QUANTITY}")
            )
            continue
        name, version = split_name_version(card_text)
        if not name:
            parsed.issues.append(
                _issue(line_number, line, ImportIssueReason.PARSE_ERROR, f"Expected a line like '{LINE_FORMAT_EXAMPLE}'")
            )
            continue

        key = card_name_key(name, version)
        existing = merged.get(key)
        if existing is None:
            merged[key] = DeckLine(line_number, line, quantity, name, version)
        else:
            merged[key] = dataclasses.replace(existing, quantity=existing.quantity + quantity)

    for deck_line in merged.values():
        if deck_line.quantity > MAX_QUANTITY:
            parsed.issues.append(
                _issue(
                    deck_line.line_number,
                    deck_line.raw,
                    ImportIssueReason.INVALID_QUANTITY,
                    f"{deck_line.quantity} copies in total; the limit is {MAX_QUANTITY} per card",
                )
            )
        else:
            parsed.lines.append(deck_line)
    return parsed


def _merge_imported(cards: list[ImportedCard], card: ImportedCard) -> None:
    """Different spellings can resolve to the same printing; combine them."""
    for index, existing in enumerate(cards):
        if (existing.set_code, existing.number) == (card.set_code, card.number):
            cards[index] = existing.model_copy(update={"quantity": existing.quantity + card.quantity})
            return
    cards.append(card)


async def resolve_deck_lines(
    client: LorcastClient, lines: Sequence[DeckLine]
) -> tuple[list[ImportedCard], list[ImportIssue]]:
    """Look up each line one at a time. A failure for one line never stops the others."""
    cards: list[ImportedCard] = []
    issues: list[ImportIssue] = []
    for deck_line in lines:
        try:
            card = await client.search_card(deck_line.name, deck_line.version)
        except LorcastError as exc:
            reason = _CARD_ERROR_TO_IMPORT_REASON.get(exc.reason, ImportIssueReason.UPSTREAM_UNAVAILABLE)
            issues.append(_issue(deck_line.line_number, deck_line.raw, reason, exc.detail))
        except Exception:
            logger.exception("Unexpected error resolving import line %d: %r", deck_line.line_number, deck_line.raw)
            issues.append(
                _issue(
                    deck_line.line_number,
                    deck_line.raw,
                    ImportIssueReason.UPSTREAM_UNAVAILABLE,
                    "Unexpected error while looking up this card",
                )
            )
        else:
            logger.debug(
                "Line %d '%s' -> set %s #%s",
                deck_line.line_number,
                deck_line.display_name,
                card.card_set.code,
                card.collector_number,
            )
            _merge_imported(
                cards,
                ImportedCard(
                    set_code=card.card_set.code,
                    number=card.collector_number,
                    quantity=deck_line.quantity,
                    name=card.display_name,
                    inks=list(card.inks),
                ),
            )
    return cards, issues
