"""What other domains may use from the nodes domain."""

from app.nodes.services.nodes import NodeService, NodeStatus, RunnerNode

__all__ = ["NodeStatus", "NodesFacade", "RunnerNode"]


class NodesFacade:
    def __init__(self, service: NodeService) -> None:
        self._service = service

    async def runners(self) -> list[RunnerNode]:
        """Every runner the control plane knows, with its readiness."""
        return await self._service.runners()

    async def builder_address(self) -> str | None:
        """gRPC address of a ready builder, None if there is none."""
        return await self._service.builder_address()

    async def runner_address(self, name: str) -> str | None:
        """gRPC address of a known runner, ready or not."""
        return await self._service.runner_address(name)

    async def runner_names(self) -> list[str]:
        """Names of every known runner, ready or not."""
        return await self._service.runner_names()
