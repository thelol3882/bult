"""Nodes for users: read-only status of the platform's machines."""

from fastapi import APIRouter

from app.auth.deps import CurrentUser
from app.nodes.deps import NodeServiceDep, ReplicaCountsDep
from app.nodes.schemas.nodes import NodeOut

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    service: NodeServiceDep, replica_counts: ReplicaCountsDep, user: CurrentUser
) -> list[NodeOut]:
    counts = await replica_counts()
    return [
        NodeOut.from_view(view, counts.get(view.name, 0))
        for view in await service.views()
    ]
