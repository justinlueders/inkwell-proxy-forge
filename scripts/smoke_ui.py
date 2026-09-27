# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Manual UI check with Playwright and the installed Edge: python -m scripts.smoke_ui [base_url]

Requires `pip install playwright` (not a project dependency).
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
OUTPUT_DIR = Path("smoke_output")
VIEWPORT = {"width": 1400, "height": 1000}
GENERATE_TIMEOUT_MS = 60_000
CARDS = (("010", "007", "3"), ("p1", "1", "1"), ("10", "170", "1"), ("10", "7", "1"), ("10", "9999", "1"))


def add_card(page, set_code: str, number: str, quantity: str) -> None:
    page.fill("#set-input", set_code)
    page.fill("#number-input", number)
    page.fill("#quantity-input", quantity)
    page.press("#quantity-input", "Enter")


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    OUTPUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        page = browser.new_page(viewport=VIEWPORT)
        console_errors: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(base_url)
        page.wait_for_selector("#card-form-fields:not([disabled])")

        # Validation: empty submit and bad quantity.
        page.click(".card-form__add")
        print("empty set error:", page.text_content("#set-error"))
        add_card(page, "10", "1", "0")
        print("bad qty error:", page.text_content("#quantity-error"))

        for card in CARDS:
            add_card(page, *card)
        rows = page.locator(".card-row").count()
        print("rows:", rows, "cards:", page.text_content("#summary-cards"), "pages:", page.text_content("#summary-pages"))
        page.screenshot(path=OUTPUT_DIR / "ui_list.png", full_page=True)

        page.click("#generate-button")
        page.wait_for_selector("#viewer:not([hidden])", timeout=GENERATE_TIMEOUT_MS)
        print("counter:", page.text_content("#page-counter"))
        print("error title:", page.text_content("#error-title"))
        print("error items:", page.locator(".error-panel__item").all_text_contents())
        print("request id:", page.text_content("#error-request-id"))
        print("print pages:", page.locator(".print-root__page").count())
        page.screenshot(path=OUTPUT_DIR / "ui_result.png", full_page=True)

        page.emulate_media(media="print")
        page.screenshot(path=OUTPUT_DIR / "ui_print.png")
        print("console errors:", console_errors)
        browser.close()


if __name__ == "__main__":
    main()
