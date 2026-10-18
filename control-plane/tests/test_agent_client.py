"""AgentClients: logs against a stub stream, and channels that follow the directory (no network)."""

import asyncio
from typing import Any

import grpc
import pytest
from bult.agent.v1 import agent_pb2

from app.agents.client import AgentClients, UnknownNodeError


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


class StubDirectory:
    def __init__(self) -> None:
        self.builder: str | None = "builder:50051"
        self.runners: dict[str, str] = {"node-a": "10.0.0.5:50051"}

    async def builder_address(self) -> str | None:
        return self.builder

    async def runner_address(self, name: str) -> str | None:
        return self.runners.get(name)

    async def runner_names(self) -> list[str]:
        return list(self.runners)


def test_logs_joins_chunks_asks_without_follow_and_tolerates_bad_utf8():
    async def scenario() -> tuple[str, StubRuntime]:
        clients = AgentClients(StubDirectory())
        stub = StubRuntime([b"hello ", b"wor", b"ld\n\xff\xfe broken\n"])

        async def runner_stub(node: str) -> Any:
            return stub

        clients._runner_stub = runner_stub  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
        try:
            return await clients.logs("node-a", "d1-r0", 50), stub
        finally:
            await clients.close()

    text, stub = asyncio.run(scenario())

    assert text.splitlines()[0] == "hello world"
    assert "broken" in text
    [(request, _)] = stub.requests
    assert (request.replica_id, request.follow, request.tail_lines) == ("d1-r0", False, 50)


def test_channels_are_created_lazily_reused_and_follow_an_address_change():
    async def scenario() -> None:
        directory = StubDirectory()
        clients = AgentClients(directory)
        assert clients._channels == {}  # pyright: ignore[reportPrivateUsage]

        try:
            first = await clients._runner_stub("node-a")  # pyright: ignore[reportPrivateUsage]
            again = await clients._runner_stub("node-a")  # pyright: ignore[reportPrivateUsage]
            channel = clients._channels["runner:node-a"].channel  # pyright: ignore[reportPrivateUsage]
            assert first is not again  # a stub is cheap; the channel is what is shared
            assert clients._channels["runner:node-a"].channel is channel  # pyright: ignore[reportPrivateUsage]

            directory.runners["node-a"] = "10.0.0.9:50051"
            await clients._runner_stub("node-a")  # pyright: ignore[reportPrivateUsage]
            replaced = clients._channels["runner:node-a"]  # pyright: ignore[reportPrivateUsage]
            assert replaced.address == "10.0.0.9:50051"
            assert replaced.channel is not channel
        finally:
            await clients.close()

        assert clients._channels == {}  # pyright: ignore[reportPrivateUsage]

    asyncio.run(scenario())


def test_unknown_runner_and_missing_builder():
    async def scenario() -> None:
        directory = StubDirectory()
        directory.builder = None
        clients = AgentClients(directory)
        try:
            with pytest.raises(UnknownNodeError):
                await clients.remove_replica("node-z", "d1-r0")
            with pytest.raises(grpc.aio.AioRpcError) as info:
                await clients.get_deploy("d1")
            assert info.value.code() == grpc.StatusCode.UNAVAILABLE
        finally:
            await clients.close()

    asyncio.run(scenario())
