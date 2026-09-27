# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import io
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from PIL import Image

from server.config import LORCAST_API_BASE
from server.lorcast import LorcastClient
from server.rate_limiter import RateLimiter

IMAGE_HOST = "https://cards.test"
PORTRAIT_SIZE = (674, 940)
SETS_PAYLOAD = {
    "results": [
        {"id": "set_10", "code": "10", "name": "Whispers in the Well"},
        {"id": "set_p1", "code": "P1", "name": "Promo Set 1"},
    ]
}

Handler = Callable[[httpx.Request], httpx.Response]


def make_image_bytes(size: tuple[int, int] = PORTRAIT_SIZE, mode: str = "RGB", image_format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, "red" if mode == "RGB" else (255, 0, 0, 0)).save(buffer, format=image_format)
    return buffer.getvalue()


def card_payload(set_code: str = "10", number: str = "7", *, layout: str = "normal", image: str | None = "img") -> dict[str, Any]:
    digital = {"large": f"{IMAGE_HOST}/{image}.png"} if image else {}
    return {
        "id": f"crd_{set_code}_{number}",
        "name": "Eilonwy",
        "version": "Princess of Llyr",
        "layout": layout,
        "image_uris": {"digital": digital},
        "collector_number": number,
        "ink": "Amber",
        "inks": ["Amber"],
        "set": {"id": f"set_{set_code}", "code": set_code, "name": "Test Set"},
    }


def named_card_payload(name: str, version: str | None, set_code: str = "10", number: str = "7") -> dict[str, Any]:
    return {**card_payload(set_code, number), "name": name, "version": version}


def search_response(*cards: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"results": list(cards)})


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_client(sleeps: list[float]) -> Callable[[Handler], LorcastClient]:
    def factory(handler: Handler) -> LorcastClient:
        async def record_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return LorcastClient(http, RateLimiter(0, sleep=no_sleep), base_url=LORCAST_API_BASE, sleep=record_sleep)

    return factory


def default_handler(request: httpx.Request) -> httpx.Response:
    """Sets list, one known card per path, and a PNG for every image URL."""
    url = str(request.url)
    if url.startswith(IMAGE_HOST):
        return httpx.Response(200, content=make_image_bytes())
    path = request.url.path
    if path.endswith("/sets"):
        return httpx.Response(200, json=SETS_PAYLOAD)
    if "/cards/" in path:
        _, _, set_code, number = path.rsplit("/", 3)
        if number == "9999":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=card_payload(set_code, number))
    return httpx.Response(404)
