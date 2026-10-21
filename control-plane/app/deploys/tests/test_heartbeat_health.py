"""Replica states in the heartbeat: stored on the replica rows; old agents keep working."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import NODE_TOKENS, add_running_deploy

URL = "/internal/nodes/heartbeat"
BEAT: dict[str, Any] = {"name": "node-a", "address": "10.0.0.5:50051", "role": "runner"}
USAGE = {"cpu_cores": 0.1, "cpu_limit_pct": 20.0, "mem_bytes": 1, "mem_limit_bytes": 2}


def _post(client: TestClient, **extra: Any):
    return client.post(
        URL,
        json={**BEAT, **extra},
        headers={"Authorization": f"Bearer {NODE_TOKENS['node-a']}"},
    )


def _row(uow: InMemoryDeploysUoW):
    return asyncio.run(uow.replicas.get_running(["d1-r0"]))[0]


def test_an_exit_in_the_heartbeat_marks_the_replica_dead(
    anon_client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    asyncio.run(add_running_deploy(deploys_uow, "d1", "blog"))
    asyncio.run(deploys_uow.replicas.update("d1-r0", placed_at=datetime(2026, 10, 1, tzinfo=UTC)))

    resp = _post(
        anon_client,
        reports_replicas=True,
        replicas=[
            {
                "replica_id": "d1-r0",
                "state": "exited",
                "exit_code": 1,
                "oom_killed": False,
                "healthy": False,
                "finished_at": "2026-10-21T09:30:05Z",
            }
        ],
    )

    assert resp.status_code == 204
    row = _row(deploys_uow)
    assert (row.state, row.exit_code, row.serving) == ("exited", 1, False)


def test_a_running_replica_reports_health_and_usage_in_one_entry(
    anon_client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    asyncio.run(add_running_deploy(deploys_uow, "d1", "blog"))

    resp = _post(
        anon_client,
        replicas=[{"replica_id": "d1-r0", "state": "running", "healthy": False, **USAGE}],
    )

    assert resp.status_code == 204
    assert (_row(deploys_uow).state, _row(deploys_uow).healthy) == ("running", False)


def test_an_older_agent_without_states_changes_nothing(
    anon_client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    asyncio.run(add_running_deploy(deploys_uow, "d1", "blog"))

    assert _post(anon_client, replicas=[{"replica_id": "d1-r0", **USAGE}]).status_code == 204

    assert _row(deploys_uow).serving


def test_a_report_for_another_nodes_replica_is_ignored(
    anon_client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    asyncio.run(add_running_deploy(deploys_uow, "d1", "blog", [("node-b", 30001)]))

    _post(anon_client, replicas=[{"replica_id": "d1-r0", "state": "exited", "exit_code": 1}])

    assert _row(deploys_uow).state == "running"


def test_a_bad_state_is_rejected(anon_client: TestClient):
    resp = _post(anon_client, replicas=[{"replica_id": "d1-r0", "state": "sleeping"}])

    assert resp.status_code == 422
