"""NodeRepository on PostgreSQL: ORM rows in, Node dataclasses out."""

from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.nodes.models.nodes import NodeModel
from app.nodes.repositories.nodes import Node, NodeRole


class SqlNodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, node: Node) -> Node:
        values = {
            "address": node.address,
            "role": node.role,
            "version": node.version,
            "cpus": node.cpus,
            "memory_bytes": node.memory_bytes,
            "last_seen_at": node.last_seen_at,
        }
        stmt = (
            insert(NodeModel)
            .values(name=node.name, **values)
            .on_conflict_do_update(
                index_elements=[NodeModel.name],
                # on_conflict_do_update does not run the column's onupdate
                set_={**values, "updated_at": func.now()},
            )
            .returning(NodeModel)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one()
        return _to_domain(row)

    async def list(self) -> list[Node]:
        rows = await self._session.scalars(select(NodeModel).order_by(NodeModel.name))
        return [_to_domain(row) for row in rows.all()]


def _to_domain(row: NodeModel) -> Node:
    return Node(
        name=row.name,
        address=row.address,
        role=cast(NodeRole, row.role),
        last_seen_at=row.last_seen_at,
        version=row.version,
        cpus=row.cpus,
        memory_bytes=row.memory_bytes,
        created_at=row.created_at,
    )
