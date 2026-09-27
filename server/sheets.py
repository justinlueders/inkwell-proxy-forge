# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Compose card images onto 300 DPI US Letter pages."""

import base64
import io
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps

from server.config import (
    CARD_GAP_X_PX,
    CARD_GAP_Y_PX,
    CARD_HEIGHT_PX,
    CARD_WIDTH_PX,
    CARDS_PER_PAGE,
    CROP_MARK_COLOR,
    CROP_MARK_GAP_PX,
    CROP_MARK_LENGTH_PX,
    CROP_MARK_WIDTH_PX,
    GRID_COLUMNS,
    GRID_LEFT_PX,
    GRID_ROWS,
    GRID_TOP_PX,
    JPEG_QUALITY,
    PAGE_BACKGROUND,
    PAGE_HEIGHT_PX,
    PAGE_WIDTH_PX,
    PLACEHOLDER_BORDER,
    PLACEHOLDER_BORDER_WIDTH_PX,
    PLACEHOLDER_FILL,
    PLACEHOLDER_FONT_SIZE_PX,
    PLACEHOLDER_LINE_SPACING_PX,
    PLACEHOLDER_TEXT_COLOR,
    PRINT_DPI,
)
from server.models import CardErrorReason

logger = logging.getLogger(__name__)

RGB_MODE = "RGB"
RGBA_MODE = "RGBA"
ALPHA_CHANNEL = "A"
TRANSPARENCY_INFO_KEY = "transparency"
ENUM_WORD_SEPARATOR = "_"
MODES_WITH_ALPHA = frozenset({"RGBA", "LA", "PA"})
JPEG_FORMAT = "JPEG"
CENTER_ANCHOR = "mm"
CENTER_ALIGN = "center"
TEXT_ENCODING = "ascii"
LANDSCAPE_ROTATION = Image.Transpose.ROTATE_90
CENTER = (0.5, 0.5)


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def origin(self) -> tuple[int, int]:
        return self.left, self.top


@dataclass(frozen=True)
class Placeholder:
    set_code: str
    number: str
    reason: CardErrorReason


SlotContent = Image.Image | Placeholder


@dataclass(frozen=True)
class SheetEntry:
    content: SlotContent
    quantity: int


# --- Layout ------------------------------------------------------------------


def slot_boxes() -> list[Box]:
    """Card slots on one page, row by row, separated by cutting gaps and centered."""
    boxes: list[Box] = []
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            left = GRID_LEFT_PX + column * (CARD_WIDTH_PX + CARD_GAP_X_PX)
            top = GRID_TOP_PX + row * (CARD_HEIGHT_PX + CARD_GAP_Y_PX)
            boxes.append(Box(left, top, left + CARD_WIDTH_PX, top + CARD_HEIGHT_PX))
    return boxes


def page_count(card_count: int) -> int:
    return -(-card_count // CARDS_PER_PAGE)


def chunk(items: Sequence[SlotContent], size: int) -> Iterator[Sequence[SlotContent]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# --- Card images -------------------------------------------------------------


def flatten_onto_background(image: Image.Image) -> Image.Image:
    """Composite transparent pixels (e.g. rounded corners) onto the page color so they don't print black."""
    has_alpha = image.mode in MODES_WITH_ALPHA or TRANSPARENCY_INFO_KEY in image.info
    if not has_alpha:
        return image.convert(RGB_MODE)
    rgba = image.convert(RGBA_MODE)
    background = Image.new(RGB_MODE, rgba.size, PAGE_BACKGROUND)
    background.paste(rgba, mask=rgba.getchannel(ALPHA_CHANNEL))
    return background


def orient_portrait(image: Image.Image) -> Image.Image:
    """Rotate wide images into the portrait slot.

    Lorcast already serves Location art pre-rotated to portrait, so orientation is decided from the
    pixels, not the card's layout field.
    """
    if image.width > image.height:
        return image.transpose(LANDSCAPE_ROTATION)
    return image


def fit_card_image(image: Image.Image) -> Image.Image:
    """Produce an exactly card-sized RGB image: flatten, orient, cover-resize, center-crop."""
    prepared = orient_portrait(flatten_onto_background(image))
    return ImageOps.fit(
        prepared,
        (CARD_WIDTH_PX, CARD_HEIGHT_PX),
        method=Image.Resampling.LANCZOS,
        centering=CENTER,
    )


def render_placeholder(placeholder: Placeholder) -> Image.Image:
    card = Image.new(RGB_MODE, (CARD_WIDTH_PX, CARD_HEIGHT_PX), PLACEHOLDER_FILL)
    draw = ImageDraw.Draw(card)
    inset = PLACEHOLDER_BORDER_WIDTH_PX // 2
    draw.rectangle(
        (inset, inset, CARD_WIDTH_PX - 1 - inset, CARD_HEIGHT_PX - 1 - inset),
        outline=PLACEHOLDER_BORDER,
        width=PLACEHOLDER_BORDER_WIDTH_PX,
    )
    font = ImageFont.load_default(size=PLACEHOLDER_FONT_SIZE_PX)
    reason_text = placeholder.reason.value.replace(ENUM_WORD_SEPARATOR, " ")
    label = f"Set {_printable(placeholder.set_code)}\nCard {_printable(placeholder.number)}\n\n{reason_text}"
    draw.multiline_text(
        (CARD_WIDTH_PX // 2, CARD_HEIGHT_PX // 2),
        label,
        fill=PLACEHOLDER_TEXT_COLOR,
        font=font,
        anchor=CENTER_ANCHOR,
        align=CENTER_ALIGN,
        spacing=PLACEHOLDER_LINE_SPACING_PX,
    )
    return card


def _printable(value: str) -> str:
    """The default font only covers basic Latin; replace anything else so drawing can't fail."""
    return value.encode(TEXT_ENCODING, errors="replace").decode(TEXT_ENCODING)


def render_slot(content: SlotContent) -> Image.Image:
    if isinstance(content, Placeholder):
        return render_placeholder(content)
    return fit_card_image(content)


# --- Pages -------------------------------------------------------------------


def draw_crop_marks(draw: ImageDraw.ImageDraw) -> None:
    """Short cut guides at every card edge, only in the page margins so they never touch card art."""
    boxes = slot_boxes()
    edges_x = sorted({x for box in boxes for x in (box.left, box.right)})
    edges_y = sorted({y for box in boxes for y in (box.top, box.bottom)})
    grid_right = max(edges_x)
    grid_bottom = max(edges_y)
    vertical_length = min(CROP_MARK_LENGTH_PX, GRID_TOP_PX - CROP_MARK_GAP_PX)
    horizontal_length = min(CROP_MARK_LENGTH_PX, GRID_LEFT_PX - CROP_MARK_GAP_PX)
    style = {"fill": CROP_MARK_COLOR, "width": CROP_MARK_WIDTH_PX}

    if vertical_length > 0:
        top_end = GRID_TOP_PX - CROP_MARK_GAP_PX
        bottom_start = grid_bottom + CROP_MARK_GAP_PX
        for x in edges_x:
            draw.line((x, top_end - vertical_length, x, top_end), **style)
            draw.line((x, bottom_start, x, bottom_start + vertical_length), **style)

    if horizontal_length > 0:
        left_end = GRID_LEFT_PX - CROP_MARK_GAP_PX
        right_start = grid_right + CROP_MARK_GAP_PX
        for y in edges_y:
            draw.line((left_end - horizontal_length, y, left_end, y), **style)
            draw.line((right_start, y, right_start + horizontal_length, y), **style)


def compose_page(slots: Sequence[Image.Image]) -> Image.Image:
    if len(slots) > CARDS_PER_PAGE:
        raise ValueError(f"A page holds at most {CARDS_PER_PAGE} cards, got {len(slots)}")
    page = Image.new(RGB_MODE, (PAGE_WIDTH_PX, PAGE_HEIGHT_PX), PAGE_BACKGROUND)
    for slot_image, box in zip(slots, slot_boxes(), strict=False):
        page.paste(slot_image, box.origin)
    draw_crop_marks(ImageDraw.Draw(page))
    return page


def encode_jpeg(page: Image.Image) -> bytes:
    buffer = io.BytesIO()
    page.save(buffer, format=JPEG_FORMAT, quality=JPEG_QUALITY, dpi=(PRINT_DPI, PRINT_DPI))
    return buffer.getvalue()


def render_pages(entries: Sequence[SheetEntry]) -> list[bytes]:
    """Render every entry once, repeat by quantity, and return one JPEG per page. CPU-bound: call off the event loop."""
    rendered = [(render_slot(entry.content), entry.quantity) for entry in entries]
    slots = [image for image, quantity in rendered for _ in range(quantity)]
    pages: list[bytes] = []
    for page_slots in chunk(slots, CARDS_PER_PAGE):
        page = compose_page(page_slots)
        pages.append(encode_jpeg(page))
        page.close()
    logger.debug("Rendered %d page(s) from %d card(s)", len(pages), len(slots))
    return pages


def render_pages_base64(entries: Sequence[SheetEntry]) -> list[str]:
    return [base64.b64encode(page).decode(TEXT_ENCODING) for page in render_pages(entries)]
