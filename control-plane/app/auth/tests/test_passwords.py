"""PasswordHasher must not block the event loop."""

import asyncio
import time

from app.auth.services.passwords import PasswordHasher


def test_verify_keeps_event_loop_responsive() -> None:
    asyncio.run(_verify_while_ticking())


async def _verify_while_ticking() -> None:
    hasher = PasswordHasher()
    password_hash = await hasher.hash("secret-password")

    worst_gap = 0.0
    stop = False

    async def ticker() -> None:
        nonlocal worst_gap
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.001)
            now = time.perf_counter()
            worst_gap = max(worst_gap, now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)
    worst_gap = 0.0

    started = time.perf_counter()
    ok, _ = await hasher.verify("secret-password", password_hash)
    verify_time = time.perf_counter() - started

    stop = True
    await task

    assert ok
    assert worst_gap < verify_time / 3
