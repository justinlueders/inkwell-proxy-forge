# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Justin Lueders

import asyncio

import pytest

from server.rate_limiter import RateLimiter

INTERVAL = 0.075


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.acquired_at: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


async def test_consecutive_acquires_are_spaced() -> None:
    clock = FakeClock()
    limiter = RateLimiter(INTERVAL, clock=clock, sleep=clock.sleep)
    times = []
    for _ in range(4):
        await limiter.acquire()
        times.append(clock.now)
    gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
    assert all(gap >= INTERVAL - 1e-9 for gap in gaps)


async def test_no_wait_when_enough_time_has_passed() -> None:
    clock = FakeClock()
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    limiter = RateLimiter(INTERVAL, clock=clock, sleep=record)
    await limiter.acquire()
    clock.now += INTERVAL * 2
    await limiter.acquire()
    assert slept == []


async def test_concurrent_callers_share_the_spacing() -> None:
    clock = FakeClock()
    limiter = RateLimiter(INTERVAL, clock=clock, sleep=clock.sleep)
    times: list[float] = []

    async def worker() -> None:
        await limiter.acquire()
        times.append(clock.now)

    await asyncio.gather(*(worker() for _ in range(5)))
    times.sort()
    assert times[-1] - times[0] == pytest.approx(INTERVAL * 4)


def test_negative_interval_is_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimiter(-1)
