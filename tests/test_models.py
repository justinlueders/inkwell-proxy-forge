import pytest
from pydantic import ValidationError

from server.config import MAX_ENTRIES_PER_REQUEST, MAX_QUANTITY, MAX_TOTAL_CARDS, MIN_QUANTITY
from server.models import CardLayout, CardRequest, LorcastCard, SheetRequest
from tests.conftest import card_payload


def test_card_request_normalizes_and_defaults_quantity() -> None:
    card = CardRequest(set_code=" 010 ", number="007")
    assert (card.set_code, card.number, card.quantity) == ("10", "7", MIN_QUANTITY)


@pytest.mark.parametrize("field", ["set_code", "number"])
def test_card_request_rejects_blank_identifiers(field: str) -> None:
    values = {"set_code": "10", "number": "1", field: "   "}
    with pytest.raises(ValidationError):
        CardRequest(**values)


@pytest.mark.parametrize("quantity", [MIN_QUANTITY - 1, MAX_QUANTITY + 1])
def test_card_request_rejects_out_of_range_quantity(quantity: int) -> None:
    with pytest.raises(ValidationError):
        CardRequest(set_code="10", number="1", quantity=quantity)


def test_sheet_request_rejects_empty_list() -> None:
    with pytest.raises(ValidationError):
        SheetRequest(cards=[])


def test_sheet_request_rejects_too_many_entries() -> None:
    cards = [CardRequest(set_code="10", number=str(n)) for n in range(1, MAX_ENTRIES_PER_REQUEST + 2)]
    with pytest.raises(ValidationError):
        SheetRequest(cards=cards)


def test_sheet_request_rejects_total_over_limit() -> None:
    per_card = MAX_QUANTITY
    count = MAX_TOTAL_CARDS // per_card + 1
    cards = [CardRequest(set_code="10", number=str(n), quantity=per_card) for n in range(1, count + 1)]
    with pytest.raises(ValidationError, match="exceeds the limit"):
        SheetRequest(cards=cards)


def test_sheet_request_merges_duplicates_case_insensitively() -> None:
    request = SheetRequest(
        cards=[
            CardRequest(set_code="p1", number="1", quantity=2),
            CardRequest(set_code="10", number="7"),
            CardRequest(set_code="P1", number="001", quantity=3),
        ]
    )
    merged = request.merged_cards()
    assert [(card.set_code, card.number, card.quantity) for card in merged] == [("p1", "1", 5), ("10", "7", 1)]


def test_sheet_request_rejects_merged_quantity_over_cap() -> None:
    with pytest.raises(ValidationError, match="limit is"):
        SheetRequest(
            cards=[
                CardRequest(set_code="10", number="7", quantity=MAX_QUANTITY),
                CardRequest(set_code="10", number="007", quantity=MIN_QUANTITY),
            ]
        )


def test_lorcast_card_unknown_layout_falls_back_to_normal() -> None:
    card = LorcastCard.model_validate(card_payload(layout="hexagon"))
    assert card.layout is CardLayout.NORMAL
