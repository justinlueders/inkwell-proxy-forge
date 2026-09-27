# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Regenerate the README screenshots from a running server: python -m scripts.capture_docs [base_url]

Requires `pip install playwright` (not a project dependency) and live Lorcast access.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DOCS_DIR = Path("docs")
VIEWPORT = {"width": 1400, "height": 1000}
REQUEST_TIMEOUT_MS = 90_000
DIALOG_DECK = """\
4 Hercules - Spectral Demigod
2 Bunch of Balloons
2 Ares - God of War
3 Liquidator - Iced Over
4 Scrooge McDuck - Ghostly Ebenezer
4 Scrooge's Counting House - Ebenezer's Office
4 Webby's Diary
4 Aladdin - Barreling Through
"""
SHEET_DECK = """\
1 Hercules - Spectral Demigod
1 Bunch of Balloons
1 Ares - God of War
1 Liquidator - Iced Over
1 Scrooge McDuck - Ghostly Ebenezer
1 Scrooge's Counting House - Ebenezer's Office
1 Webby's Diary
1 Aladdin - Barreling Through
1 Maleficent - Monstrous Dragon
"""


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    DOCS_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(base_url)
        page.wait_for_selector("#import-open-button:not([disabled])")

        page.click("#import-open-button")
        page.fill("#import-text", DIALOG_DECK)
        page.screenshot(path=DOCS_DIR / "import-dialog.png")

        page.fill("#import-text", SHEET_DECK)
        page.click("#import-submit-button")
        page.wait_for_selector("#import-dialog:not([open])", state="attached", timeout=REQUEST_TIMEOUT_MS)

        page.click("#generate-button")
        page.wait_for_selector("#viewer:not([hidden])", timeout=REQUEST_TIMEOUT_MS)
        page.wait_for_function("document.querySelector('#viewer-image')?.complete")
        page.screenshot(path=DOCS_DIR / "screenshot.png")
        browser.close()


if __name__ == "__main__":
    main()
