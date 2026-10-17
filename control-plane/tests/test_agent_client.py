"""AgentClients.logs against a stub stream (no network)."""

import asyncio
from typing import Any

from bult.agent.v1 import agent_pb2

from app.agents.client import AgentClients


class StubRuntime:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.requests: list[Any] = []

    def Logs(self, request: Any, timeout: float):  # noqa: N802 - the generated name
        self.requests.append((request, timeout))

        async def stream():
            for chunk in self.chunks:
                yield agent_pb2.LogsResponse(data=chunk)

        return stream()


def test_logs_joins_chunks_asks_without_follow_and_tolerates_bad_utf8():
    async def scenario() -> tuple[str, StubRuntime]:
        clients = AgentClients("builder:1", {"node-a": "10.0.0.5:50051"})
        stub = StubRuntime([b"hello ", b"wor", b"ld\n\xff\xfe broken\n"])
        clients._runners["node-a"] = stub  # pyright: ignore[reportArgumentType, reportPrivateUsage]
        try:
            return await clients.logs("node-a", "d1-r0", 50), stub
        finally:
            await clients.close()

    text, stub = asyncio.run(scenario())

    assert text.splitlines()[0] == "hello world"
    assert "broken" in text
    [(request, _)] = stub.requests
    assert (request.replica_id, request.follow, request.tail_lines) == ("d1-r0", False, 50)
