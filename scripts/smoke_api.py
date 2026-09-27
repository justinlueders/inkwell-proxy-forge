# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Manual end-to-end check against a running server: python -m scripts.smoke_api [base_url]"""

import base64
import sys
from pathlib import Path

import httpx

from server.config import API_SHEET_ROUTE, REQUEST_ID_HEADER

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
OUTPUT_DIR = Path("smoke_output")
TIMEOUT_SECONDS = 120.0
SAMPLE_BODY = {
    "cards": [
        {"set_code": "010", "number": "007", "quantity": 4},
        {"set_code": "p1", "number": "1", "quantity": 1},
        {"set_code": "10", "number": "170", "quantity": 2},
        {"set_code": "10", "number": "7", "quantity": 1},
        {"set_code": "10", "number": "9999", "quantity": 1},
    ]
}
INVALID_BODY = {"cards": [{"set_code": " ", "number": "1", "quantity": 0}]}


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    OUTPUT_DIR.mkdir(exist_ok=True)
    with httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS) as client:
        response = client.post(API_SHEET_ROUTE, json=SAMPLE_BODY)
        data = response.json()
        print(response.status_code, response.headers.get(REQUEST_ID_HEADER))
        print({key: value for key, value in data.items() if key != "pages"})
        for index, page in enumerate(data["pages"], start=1):
            path = OUTPUT_DIR / f"page_{index}.jpg"
            path.write_bytes(base64.b64decode(page))
            print("wrote", path)

        invalid = client.post(API_SHEET_ROUTE, json=INVALID_BODY)
        print(invalid.status_code, invalid.json())


if __name__ == "__main__":
    main()
