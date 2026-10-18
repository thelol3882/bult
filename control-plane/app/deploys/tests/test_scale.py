"""PUT /apps/{name}/replicas, replicas in the API, per-replica logs."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import (
    HOST_PORT,
    NODE_B,
    FakeAgentClients,
    FakeNodes,
    FakeRoutes,
    add_running_deploy,
    make_worker,
    run_deploys,
)

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}
IMAGE = "registry.local/blog@sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


@pytest.fixture
def two_nodes(nodes: FakeNodes) -> FakeNodes:
    nodes.add(*NODE_B)
    return nodes


def _scale(client: TestClient, replicas: int):
    return client.put("/apps/blog/replicas", json={"replicas": replicas})


def _running_with(
    uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    placements: list[tuple[str, int]],
) -> None:
    async def add() -> None:
        await add_running_deploy(uow, "d1", "blog", placements, image=IMAGE)

    asyncio.run(add())
    for index, (node, port) in enumerate(placements):
        agents.seed_replica(f"d1-r{index}", "blog", node=node, port=port)


def _rows(uow: InMemoryDeploysUoW) -> list[tuple[int, str]]:
    return [(r.index, r.node) for r in asyncio.run(uow.replicas.list_running(["d1"]))]


def test_scaling_up_adds_replicas_to_the_running_deploy_without_a_build(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])

    resp = _scale(client, 3)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["replicas"] == 3
    assert (body["deploy"]["desired_replicas"], body["deploy"]["ready_replicas"]) == (3, 3)
    assert agents.start_calls == [] and agents.get_calls == 0
    assert [c["replica_id"] for c in agents.run_calls] == ["d1-r1", "d1-r2"]
    # node-b has none yet, so it takes the next one; then node-a and node-b are level.
    assert _rows(deploys_uow) == [(0, "node-a"), (1, "node-b"), (2, "node-a")]
    assert client.get("/apps/blog").json()["replicas"] == 3
    [route] = routes.applied[-1]
    assert len(route.upstreams) == 3
    assert asyncio.run(deploys_uow.deploys.list_running("blog"))[0].id == "d1"  # same deploy


def test_scaling_down_removes_the_highest_numbered_replicas_after_the_route_drops_them(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    monkeypatch: pytest.MonkeyPatch,
):
    _running_with(
        deploys_uow, agents, [("node-a", 30001), ("node-b", 30002), ("node-a", 30003)]
    )
    order: list[str] = []
    apply, remove = routes.apply, agents.remove_replica

    def traced_apply(*args, **kwargs) -> int:
        order.append("route")
        return apply(*args, **kwargs)

    async def traced_remove(node: str, replica_id: str) -> None:
        order.append(f"remove {replica_id}")
        await remove(node, replica_id)

    monkeypatch.setattr(routes, "apply", traced_apply)
    monkeypatch.setattr(agents, "remove_replica", traced_remove)

    resp = _scale(client, 1)

    assert resp.status_code == 200
    assert resp.json()["deploy"]["ready_replicas"] == 1
    assert order == ["route", "remove d1-r2", "remove d1-r1"]
    assert _rows(deploys_uow) == [(0, "node-a")]
    [route] = routes.applied[-1]
    assert [u.host_port for u in route.upstreams] == [30001]
    deploy = asyncio.run(deploys_uow.deploys.get("d1"))
    assert deploy is not None and (deploy.status, deploy.desired_replicas) == ("running", 1)


def test_scaling_to_zero_stops_the_app(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])

    resp = _scale(client, 0)

    assert resp.status_code == 200
    assert resp.json() == {"replicas": 0, "deploy": None}
    deploy = asyncio.run(deploys_uow.deploys.get("d1"))
    assert deploy is not None and deploy.status == "stopped"
    assert client.get("/apps/blog").json()["replicas"] == 0
    assert routes.applied_stopped[-1] == ["blog"]
    assert [c["replica_id"] for c in agents.remove_calls] == ["d1-r0"]


def test_scaling_a_stopped_app_starts_it_from_its_last_image(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])
    assert client.post("/apps/blog/stop").status_code == 204
    agents.run_calls.clear()

    resp = _scale(client, 2)

    assert resp.status_code == 200
    started = resp.json()["deploy"]
    assert (started["status"], started["desired_replicas"]) == ("starting", 2)
    assert client.get("/apps/blog").json()["replicas"] == 2

    asyncio.run(run_deploys(make_worker(deploys_uow, agents, routes)))

    assert agents.start_calls == []
    assert len(agents.run_calls) == 2
    assert len(asyncio.run(deploys_uow.replicas.list_running([started["id"]]))) == 2


def test_scaling_an_app_that_never_ran_says_to_deploy_first(
    client: TestClient, agents: FakeAgentClients
):
    resp = _scale(client, 2)

    assert resp.status_code == 409
    assert resp.json()["code"] == "nothing_to_start"
    assert agents.run_calls == []


@pytest.mark.parametrize("replicas", [-1, 6, "two", None])
def test_replicas_are_validated(client: TestClient, replicas: object):
    resp = client.put("/apps/blog/replicas", json={"replicas": replicas})

    assert resp.status_code == 422
    assert "replicas" in resp.json()["fields"]


def test_extra_fields_are_rejected(client: TestClient):
    resp = client.put("/apps/blog/replicas", json={"replicas": 2, "image": "x"})

    assert resp.status_code == 422


def test_scaling_is_refused_while_a_deploy_is_in_progress(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    asyncio.run(deploys_uow.deploys.add(Deploy(id="d2", app_name="blog", status="building")))

    resp = _scale(client, 2)

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_in_progress"


def test_scaling_up_with_no_ready_node_changes_nothing(
    client: TestClient,
    nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])
    nodes.set_ready("node-a", False)

    resp = _scale(client, 3)

    assert resp.status_code == 503
    assert resp.json()["code"] == "no_node_available"
    assert client.get("/apps/blog").json()["replicas"] == 1
    assert _rows(deploys_uow) == [(0, "node-a")]


def test_scaling_up_keeps_the_replicas_that_started_when_some_fail(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])
    agents.fail_replica_ids = {"d1-r2"}

    resp = _scale(client, 3)

    assert resp.status_code == 200
    deploy = resp.json()["deploy"]
    assert (deploy["desired_replicas"], deploy["ready_replicas"]) == (3, 2)
    assert len(_rows(deploys_uow)) == 2


def test_scaling_to_the_current_count_fills_in_missing_replicas(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001), ("node-a", 30002)])

    resp = _scale(client, 3)  # a deploy that wanted 3 but has 2 is topped up the same way
    assert resp.status_code == 200
    assert [c["replica_id"] for c in agents.run_calls] == ["d1-r2"]

    again = _scale(client, 3)
    assert again.status_code == 200
    assert len(agents.run_calls) == 1  # nothing missing now: no new RunReplica


def test_a_replica_gap_is_filled_with_the_lowest_free_index(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001), ("node-a", 30002), ("node-a", 30003)])
    asyncio.run(deploys_uow.replicas.mark_removed(["d1-r1"]))  # r1 was lost

    assert _scale(client, 3).status_code == 200

    assert [c["replica_id"] for c in agents.run_calls] == ["d1-r1"]


# the API shows replicas


def test_a_deploy_shows_its_replicas_and_how_many_are_ready(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001), ("node-b", 30002)])

    body = client.get("/apps/blog/deploys/d1").json()

    assert (body["desired_replicas"], body["ready_replicas"]) == (2, 2)
    assert body["replicas"] == [
        {"index": 0, "node": "node-a", "host_port": 30001, "status": "running"},
        {"index": 1, "node": "node-b", "host_port": 30002, "status": "running"},
    ]

    two_nodes.set_ready("node-b", False)
    body = client.get("/apps/blog/deploys/d1").json()
    assert (body["desired_replicas"], body["ready_replicas"]) == (2, 1)
    assert [r["status"] for r in body["replicas"]] == ["running", "unhealthy"]


def test_a_finished_deploy_lists_no_replicas(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    asyncio.run(
        add_running_deploy(deploys_uow, "old", "blog", [("node-a", 30001)], status="superseded")
    )

    body = client.get("/apps/blog/deploys/old").json()

    assert (body["ready_replicas"], body["replicas"]) == (0, [])
    assert "node" not in body and "host_port" not in body


# logs


def test_logs_come_from_the_requested_replica(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001), ("node-b", 30002)])
    agents.log_text = "line\n"

    body = client.get("/apps/blog/logs", params={"replica": 1}).json()

    assert body == {"deploy_id": "d1", "replica": 1, "lines": ["line"]}
    assert agents.log_calls[-1]["node"] == "node-b"
    assert agents.log_calls[-1]["replica_id"] == "d1-r1"


def test_logs_default_to_the_first_replica_on_a_ready_node(
    client: TestClient,
    two_nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
):
    _running_with(deploys_uow, agents, [("node-a", 30001), ("node-b", 30002)])
    two_nodes.set_ready("node-a", False)

    body = client.get("/apps/blog/logs").json()

    assert body["replica"] == 1
    assert agents.log_calls[-1]["node"] == "node-b"


def test_logs_of_a_replica_that_does_not_exist_are_404(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _running_with(deploys_uow, agents, [("node-a", 30001)])

    resp = client.get("/apps/blog/logs", params={"replica": 3})

    assert resp.status_code == 404
    assert resp.json()["code"] == "replica_not_found"


def test_logs_replica_index_is_validated(client: TestClient):
    assert client.get("/apps/blog/logs", params={"replica": 5}).status_code == 422
    assert client.get("/apps/blog/logs", params={"replica": -1}).status_code == 422


def test_start_after_stop_uses_the_default_of_one_replica(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _running_with(deploys_uow, agents, [("node-a", HOST_PORT), ("node-a", HOST_PORT + 1)])
    assert client.post("/apps/blog/stop").status_code == 204

    started = client.post("/apps/blog/start")

    assert started.status_code == 202
    assert started.json()["desired_replicas"] == 1
    assert client.get("/apps/blog").json()["replicas"] == 1
