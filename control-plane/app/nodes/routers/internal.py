"""Endpoints for the node agents (a node token, not a user login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.nodes.deps import NodeServiceDep
from app.nodes.schemas.nodes import HeartbeatIn
from app.nodes.services.nodes import NodeReport

router = APIRouter(prefix="/internal/nodes", tags=["internal"])

bearer = HTTPBearer(auto_error=False)  # a missing header is answered by the service, in our format


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    payload: HeartbeatIn,
    service: NodeServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    token = credentials.credentials if credentials is not None else None
    await service.heartbeat(
        NodeReport(
            name=payload.name,
            address=payload.address,
            role=payload.role,
            version=payload.version,
            cpus=payload.capacity.cpus,
            memory_bytes=payload.capacity.memory_bytes,
        ),
        token,
    )
