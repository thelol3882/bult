"""The nodes domain's public API for other domains (enforced by import-linter)."""

from typing import Annotated

from fastapi import Depends, Request

from app.nodes.services.facade import NodesFacade, NodeStatus, RunnerNode

__all__ = ["NodeStatus", "NodesFacade", "NodesFacadeDep", "RunnerNode"]


def get_nodes_facade(request: Request) -> NodesFacade:
    return request.app.state.nodes


NodesFacadeDep = Annotated[NodesFacade, Depends(get_nodes_facade)]
