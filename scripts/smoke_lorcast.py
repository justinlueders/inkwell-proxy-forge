# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Manual live check against the Lorcast API: python -m scripts.smoke_lorcast"""

import asyncio

import httpx

from server.config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT, USER_AGENT_HEADER
from server.logging_config import configure_logging
from server.lorcast import LorcastClient
from server.models import CardRequest
from server.rate_limiter import RateLimiter

SAMPLE_REQUESTS = (
    CardRequest(set_code="010", number="007"),
    CardRequest(set_code="p1", number="1"),
    CardRequest(set_code="10", number="170"),
    CardRequest(set_code="10", number="9999"),
    CardRequest(set_code="ZZZ", number="1"),
)


async def main() -> None:
    configure_logging()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, headers={USER_AGENT_HEADER: USER_AGENT}) as http:
        client = LorcastClient(http, RateLimiter(REQUEST_DELAY_SECONDS))
        await client.load_sets()
        for result in await client.fetch_all(SAMPLE_REQUESTS):
            if result.fetched:
                card, image = result.fetched.card, result.fetched.image
                print(f"OK   {result.request.set_code}/{result.request.number}: {card.display_name} "
                      f"layout={card.layout} image={image.size} mode={image.mode}")
            else:
                print(f"FAIL {result.request.set_code}/{result.request.number}: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
