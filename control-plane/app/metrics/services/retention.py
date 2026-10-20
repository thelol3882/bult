"""Periodic deletion of metric samples older than the retention."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class RetentionLoop:
    """Calls `purge` every `interval` seconds; a failed round is logged and retried."""

    def __init__(self, purge: Callable[[], Awaitable[int]], interval: float) -> None:
        self._purge = purge
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="metrics-retention")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                deleted = await self._purge()
                if deleted:
                    logger.info("metrics retention: deleted %d old sample(s)", deleted)
            except Exception:
                logger.exception("metrics retention failed")
            await asyncio.sleep(self._interval)
