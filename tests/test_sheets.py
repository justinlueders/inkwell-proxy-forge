# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import io

from PIL import Image

from server.config import (
    CARD_GAP_X_PX,
    CARD_GAP_Y_PX,
    CARD_HEIGHT_PX,
    CARD_WIDTH_PX,
    CARDS_PER_PAGE,
    GRID_LEFT_PX,
    GRID_TOP_PX,
    PAGE_BACKGROUND,
    PAGE_HEIGHT_PX,
    PAGE_WIDTH_PX,
    PLACEHOLDER_FILL,
    PRINT_DPI,
)
from server.models import CardErrorReason
from server.sheets import (
    Placeholder,
    SheetEntry,
    fit_card_image,
    page_count,
    render_pages,
    render_placeholder,
    slot_boxes,
)

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def test_page_is_us_letter_at_300_dpi() -> None:
    assert (PAGE_WIDTH_PX, PAGE_HEIGHT_PX) == (2550, 3300)
    assert (CARD_WIDTH_PX, CARD_HEIGHT_PX) == (750, 1050)


def test_grid_is_centered_and_fits() -> None:
    boxes = slot_boxes()
    assert len(boxes) == CARDS_PER_PAGE
    left = min(box.left for box in boxes)
    right = max(box.right for box in boxes)
    top = min(box.top for box in boxes)
    bottom = max(box.bottom for box in boxes)
    assert (left, top) == (GRID_LEFT_PX, GRID_TOP_PX)
    assert PAGE_WIDTH_PX - right == left
    assert PAGE_HEIGHT_PX - bottom == top
    assert top > 0


def test_slots_have_cutting_gaps_and_are_row_major() -> None:
    boxes = slot_boxes()
    assert CARD_GAP_X_PX > 0 and CARD_GAP_Y_PX > 0
    assert boxes[1].left - boxes[0].right == CARD_GAP_X_PX
    assert boxes[3].top - boxes[0].bottom == CARD_GAP_Y_PX
    assert all(box.right - box.left == CARD_WIDTH_PX and box.bottom - box.top == CARD_HEIGHT_PX for box in boxes)


def test_page_count() -> None:
    assert [page_count(n) for n in (0, 1, 9, 10, 18, 19)] == [0, 1, 1, 2, 2, 3]


def test_fit_portrait_image_is_card_sized() -> None:
    fitted = fit_card_image(Image.new("RGB", (674, 940), RED))
    assert fitted.size == (CARD_WIDTH_PX, CARD_HEIGHT_PX)
    assert fitted.mode == "RGB"


def test_wide_image_is_rotated_into_portrait_slot() -> None:
    wide = Image.new("RGB", (940, 674), RED)
    wide.paste(BLUE, (0, 0, 470, 674))  # left half blue
    fitted = fit_card_image(wide)
    assert fitted.size == (CARD_WIDTH_PX, CARD_HEIGHT_PX)
    # Rotating 90 degrees counter-clockwise moves the left half to the bottom.
    assert fitted.getpixel((CARD_WIDTH_PX // 2, CARD_HEIGHT_PX - 10)) == BLUE
    assert fitted.getpixel((CARD_WIDTH_PX // 2, 10)) == RED


def test_portrait_location_art_is_not_rotated() -> None:
    portrait = Image.new("RGB", (674, 940), RED)
    portrait.paste(BLUE, (0, 0, 674, 470))  # top half blue
    fitted = fit_card_image(portrait)
    assert fitted.getpixel((CARD_WIDTH_PX // 2, 10)) == BLUE


def test_transparency_becomes_page_background() -> None:
    transparent = Image.new("RGBA", (674, 940), (0, 0, 0, 0))
    fitted = fit_card_image(transparent)
    assert fitted.getpixel((5, 5)) == PAGE_BACKGROUND


def test_palette_image_with_transparency_is_flattened() -> None:
    palette = Image.new("P", (674, 940), 0)
    palette.info["transparency"] = 0
    assert fit_card_image(palette).getpixel((5, 5)) == PAGE_BACKGROUND


def test_placeholder_is_card_sized_with_fill() -> None:
    placeholder = render_placeholder(Placeholder("10", "9999", CardErrorReason.NOT_FOUND))
    assert placeholder.size == (CARD_WIDTH_PX, CARD_HEIGHT_PX)
    assert placeholder.getpixel((CARD_WIDTH_PX // 4, CARD_HEIGHT_PX // 6)) == PLACEHOLDER_FILL


def test_placeholder_survives_non_ascii_text() -> None:
    render_placeholder(Placeholder("Ω", "✨", CardErrorReason.UNKNOWN_SET))


def test_render_pages_repeats_quantities_and_paginates() -> None:
    entries = [
        SheetEntry(Image.new("RGB", (674, 940), RED), quantity=7),
        SheetEntry(Placeholder("10", "9999", CardErrorReason.NOT_FOUND), quantity=3),
    ]
    pages = render_pages(entries)
    assert len(pages) == 2

    with Image.open(io.BytesIO(pages[1])) as last_page:
        assert last_page.size == (PAGE_WIDTH_PX, PAGE_HEIGHT_PX)
        assert last_page.info["dpi"] == (PRINT_DPI, PRINT_DPI)
        second_slot = slot_boxes()[1]
        center = ((second_slot.left + second_slot.right) // 2, (second_slot.top + second_slot.bottom) // 2)
        # The last page holds a single placeholder; the second slot is empty page background.
        assert all(abs(a - b) <= 2 for a, b in zip(last_page.getpixel(center), PAGE_BACKGROUND, strict=True))
