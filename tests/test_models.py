import pytest
from pydantic import ValidationError

from server.config import MAX_ENTRIES_PER_REQUEST, MAX_QUANTITY, MAX_TOTAL_CARDS, MIN_QUANTITY
from server.models import CardLayout, CardRequest, ImageSize, Ink, LorcastCard, SheetRequest
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


def test_blank_image_urls_are_treated_as_missing() -> None:
    payload = card_payload()
    payload["image_uris"]["digital"] = {"small": "", "normal": " ", "large": "https://cards.test/a.avif"}
    card = LorcastCard.model_validate(payload)
    assert card.image_url(ImageSize.SMALL) is None
    assert card.image_url(ImageSize.NORMAL) is None
    assert str(card.image_url(ImageSize.LARGE)) == "https://cards.test/a.avif"


def test_lorcast_card_unknown_layout_falls_back_to_normal() -> None:
    card = LorcastCard.model_validate(card_payload(layout="hexagon"))
    assert card.layout is CardLayout.NORMAL


@pytest.mark.parametrize(
    ("ink", "inks", "expected"),
    [
        ("Amber", ["Amber"], (Ink.AMBER,)),
        (None, ["Steel"], (Ink.STEEL,)),
        ("Ruby", None, (Ink.RUBY,)),
        ("Ruby", [], (Ink.RUBY,)),
        (None, ["Amber", "Steel", "Amber"], (Ink.AMBER, Ink.STEEL)),
        (None, ["Glitter", "Emerald"], (Ink.EMERALD,)),
        (None, None, ()),
    ],
)
def test_lorcast_card_collects_inks(ink: str | None, inks: list[str] | None, expected: tuple[Ink, ...]) -> None:
    payload = {**card_payload(), "ink": ink, "inks": inks}
    assert LorcastCard.model_validate(payload).inks == expected


def test_lorcast_card_without_ink_fields_has_no_inks() -> None:
    payload = card_payload()
    del payload["ink"], payload["inks"]
    assert LorcastCard.model_validate(payload).inks == ()
