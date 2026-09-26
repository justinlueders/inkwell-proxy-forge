"""Pydantic models for Lorcast responses and the sheet API, plus shared enums."""

import logging
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from server.config import (
    CARDS_PER_PAGE,
    MAX_ENTRIES_PER_REQUEST,
    MAX_IDENTIFIER_LENGTH,
    MAX_QUANTITY,
    MAX_TOTAL_CARDS,
    MIN_QUANTITY,
    REQUEST_DELAY_SECONDS,
)
from server.normalization import normalize_identifier, set_code_key

logger = logging.getLogger(__name__)


# --- Enums -------------------------------------------------------------------


class CardLayout(StrEnum):
    NORMAL = "normal"
    LANDSCAPE = "landscape"


class Ink(StrEnum):
    AMBER = "Amber"
    AMETHYST = "Amethyst"
    EMERALD = "Emerald"
    RUBY = "Ruby"
    SAPPHIRE = "Sapphire"
    STEEL = "Steel"


class ImageSize(StrEnum):
    SMALL = "small"
    NORMAL = "normal"
    LARGE = "large"


class CardErrorReason(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN_SET = "UNKNOWN_SET"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    NO_IMAGE = "NO_IMAGE"
    IMAGE_DOWNLOAD_FAILED = "IMAGE_DOWNLOAD_FAILED"
    IMAGE_DECODE_FAILED = "IMAGE_DECODE_FAILED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"


# --- Lorcast response models -------------------------------------------------


class LorcastModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class DigitalImageUris(LorcastModel):
    small: HttpUrl | None = None
    normal: HttpUrl | None = None
    large: HttpUrl | None = None


class ImageUris(LorcastModel):
    digital: DigitalImageUris | None = None


class LorcastSet(LorcastModel):
    id: str
    code: str
    name: str


class SetsResponse(LorcastModel):
    results: list[LorcastSet]


class LorcastCard(LorcastModel):
    id: str
    name: str
    version: str | None = None
    layout: CardLayout = CardLayout.NORMAL
    image_uris: ImageUris | None = None
    collector_number: str
    card_set: LorcastSet = Field(alias="set")

    @field_validator("layout", mode="before")
    @classmethod
    def _unknown_layout_is_normal(cls, value: Any) -> Any:
        if value is None:
            return CardLayout.NORMAL
        if value not in {layout.value for layout in CardLayout}:
            logger.warning("Unknown card layout %r from Lorcast; treating as %s", value, CardLayout.NORMAL)
            return CardLayout.NORMAL
        return value

    def image_url(self, size: ImageSize) -> HttpUrl | None:
        if self.image_uris is None or self.image_uris.digital is None:
            return None
        url: HttpUrl | None = getattr(self.image_uris.digital, size.value)
        return url

    @property
    def display_name(self) -> str:
        return f"{self.name} - {self.version}" if self.version else self.name


# --- App request models ------------------------------------------------------


class CardRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    set_code: str = Field(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)
    number: str = Field(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)
    quantity: int = Field(default=MIN_QUANTITY, ge=MIN_QUANTITY, le=MAX_QUANTITY)

    @field_validator("set_code", "number")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_identifier(value)

    @property
    def merge_key(self) -> tuple[str, str]:
        return set_code_key(self.set_code), self.number


class SheetRequest(BaseModel):
    cards: list[CardRequest] = Field(min_length=1, max_length=MAX_ENTRIES_PER_REQUEST)

    @model_validator(mode="after")
    def _check_totals(self) -> Self:
        total = sum(card.quantity for card in self.cards)
        if total > MAX_TOTAL_CARDS:
            raise ValueError(f"Total cards ({total}) exceeds the limit of {MAX_TOTAL_CARDS} per sheet")
        for card in self.merged_cards():
            if card.quantity > MAX_QUANTITY:
                raise ValueError(
                    f"Set {card.set_code} card {card.number} is listed {card.quantity} times in total; "
                    f"the limit is {MAX_QUANTITY} per card"
                )
        return self

    def merged_cards(self) -> list[CardRequest]:
        """Combine entries for the same card, summing quantities and keeping first-seen order."""
        merged: dict[tuple[str, str], CardRequest] = {}
        for card in self.cards:
            existing = merged.get(card.merge_key)
            if existing is None:
                merged[card.merge_key] = card
            else:
                merged[card.merge_key] = existing.model_copy(update={"quantity": existing.quantity + card.quantity})
        return list(merged.values())

    @property
    def total_cards(self) -> int:
        return sum(card.quantity for card in self.cards)


# --- App response models -----------------------------------------------------


class CardError(BaseModel):
    set_code: str
    number: str
    reason: CardErrorReason
    detail: str


class SheetResponse(BaseModel):
    request_id: str
    pages: list[str] = Field(description="Base64-encoded 300 DPI JPEG pages")
    card_count: int
    page_count: int
    errors: list[CardError]


class ErrorResponse(BaseModel):
    request_id: str
    message: str
    details: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    sets_loaded: bool
    set_count: int


class ClientConfigResponse(BaseModel):
    """Limits shared with the browser so the UI and server enforce the same rules."""

    min_quantity: int = MIN_QUANTITY
    max_quantity: int = MAX_QUANTITY
    max_entries: int = MAX_ENTRIES_PER_REQUEST
    max_total_cards: int = MAX_TOTAL_CARDS
    max_identifier_length: int = MAX_IDENTIFIER_LENGTH
    cards_per_page: int = CARDS_PER_PAGE
    request_delay_seconds: float = REQUEST_DELAY_SECONDS
