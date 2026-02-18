from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, event: dict) -> None:
        run_id = event["run_id"]
        async with self._lock:
            subscribers = list(self._subscribers.get(run_id, set()))
        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    async def subscribe(self, run_id: str) -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[run_id].add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                self._subscribers[run_id].discard(queue)
