# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Manual UI check of the deck import dialog: python -m scripts.smoke_import_ui [base_url]

Requires `pip install playwright` (not a project dependency) and live Lorcast access.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.smoke_import import SAMPLE_DECK

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
OUTPUT_DIR = Path("smoke_output")
VIEWPORT = {"width": 1400, "height": 1000}
IMPORT_TIMEOUT_MS = 60_000


def run_import(page, text: str) -> None:
    page.fill("#import-text", text)
    page.click("#import-submit-button")
    page.wait_for_selector("#import-progress", state="hidden", timeout=IMPORT_TIMEOUT_MS)


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    OUTPUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        page = browser.new_page(viewport=VIEWPORT)
        console_errors: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(base_url)
        page.wait_for_selector("#import-open-button:not([disabled])")

        page.click("#import-open-button")
        print("dialog open:", page.eval_on_selector("#import-dialog", "d => d.open"))
        print("textarea focused:", page.evaluate("document.activeElement.id"))
        page.click("#import-submit-button")
        print("empty error:", page.text_content("#import-text-error"))

        run_import(page, SAMPLE_DECK)
        print("dialog still open:", page.eval_on_selector("#import-dialog", "d => d.open"))
        print("issues title:", page.text_content("#import-issues-title"))
        print("issues:", page.locator("#import-issue-list li").all_text_contents())
        print("remaining text:", repr(page.input_value("#import-text")))
        print("status:", page.text_content("#import-status"))
        print("rows:", page.locator(".card-row").count(), "cards:", page.text_content("#summary-cards"))
        page.screenshot(path=OUTPUT_DIR / "import_issues.png")

        page.keyboard.press("Escape")
        print("closed by Escape:", not page.eval_on_selector("#import-dialog", "d => d.open"))

        # A clean re-import of one card closes the dialog and merges into the existing row.
        page.click("#import-open-button")
        run_import(page, "1 Hercules - Spectral Demigod")
        print("closed after clean import:", not page.eval_on_selector("#import-dialog", "d => d.open"))
        print("status:", page.text_content("#import-status"))
        print("first row:", page.locator(".card-row").first.text_content())
        page.screenshot(path=OUTPUT_DIR / "import_list.png", full_page=True)
        print("console errors:", console_errors)
        browser.close()


if __name__ == "__main__":
    main()
