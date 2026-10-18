"""Watches node statuses and reacts when a node becomes unhealthy or comes back."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.nodes.services.nodes import NodeService, NodeStatus

logger = logging.getLogger(__name__)


class NodeMonitor:
    """Polls statuses; calls `on_change` when a known node flips between ready and unhealthy.

    The first check only records a baseline, unless a node is already unhealthy: the routes
    built at startup did not look at node health, so they are refreshed once.
    """

    def __init__(
        self,
        nodes: NodeService,
        on_change: Callable[[], Awaitable[None]],
        interval: float,
        initial_delay: float = 0.0,
    ) -> None:
        self._nodes = nodes
        self._on_change = on_change
        self._interval = interval
        self._initial_delay = initial_delay
        self._previous: dict[str, NodeStatus] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="node-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def check(self) -> bool:
        """One round; True if `on_change` was called."""
        current = await self._nodes.statuses()
        previous, self._previous = self._previous, current

        if previous is None:
            changed = [n for n, s in current.items() if s == "unhealthy"]
        else:
            changed = [n for n, s in current.items() if n in previous and previous[n] != s]
            for name in current.keys() - previous.keys():
                logger.info("node %s appeared (%s)", name, current[name])

        if not changed:
            return False
        for name in changed:
            logger.warning("node %s is %s", name, current[name])
        try:
            await self._on_change()
        except BaseException:
            self._previous = previous  # not handled: look at the same change again next round
            raise
        return True

    async def _run(self) -> None:
        # Right after a start the agents have not reported yet: give them time.
        await asyncio.sleep(self._initial_delay)
        while True:
            try:
                await self.check()
            except Exception:
                logger.exception("node monitor: check failed")
            await asyncio.sleep(self._interval)
