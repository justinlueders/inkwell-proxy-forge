# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

"""Global spacing between outgoing requests."""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Guarantees at least `interval_seconds` between any two `acquire()` returns, across all callers."""

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must not be negative")
        self._interval = interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_acquired = -math.inf

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._last_acquired + self._interval - self._clock()
            if wait > 0:
                logger.debug("Rate limiter waiting %.1f ms", wait * 1000)
                await self._sleep(wait)
            self._last_acquired = self._clock()
