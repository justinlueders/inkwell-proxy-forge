"""Manual live check of deck list import against a running server: python -m scripts.smoke_import [base_url]"""

import sys

import httpx

from server.config import API_IMPORT_ROUTE, REQUEST_ID_HEADER

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
TIMEOUT_SECONDS = 120.0
SAMPLE_DECK = """\
4 Hercules - Spectral Demigod
2 Bunch of Balloons
2 Ares - God of War
3 Liquidator - Iced Over
4 Scrooge McDuck - Ghostly Ebenezer
4 Scrooge's Counting House - Ebenezer's Office
4 Webby's Diary
4 Aladdin - Barreling Through
3 The Horseman Strikes!
1 Ohana Means Family
4 Red Alert
2 Agustin Madrigal - Exceptionally Kind
2 Dragon Fire
4 Gaston - Superior Archer
3 Sulley - The New Boss
2 Sulley & Boo - Scare Buddies
4 Raging Storm
3 Maleficent - Monstrous Dragon
2 Olaf - Snowman of Action
3 Recovered Page
2 Not A Real Card - Nope
bad line
"""


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    with httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS) as client:
        response = client.post(API_IMPORT_ROUTE, json={"text": SAMPLE_DECK})
        data = response.json()
        print(response.status_code, response.headers.get(REQUEST_ID_HEADER))
        for card in data.get("cards", []):
            print(f"  {card['quantity']} x set {card['set_code']:>3} #{card['number']:<4} {card['name']}")
        for issue in data.get("issues", []):
            print(f"  ISSUE line {issue['line_number']}: {issue['reason']} - {issue['detail']}")


if __name__ == "__main__":
    main()
