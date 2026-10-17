"""Stop, start, rollback and logs through the API; the worker runs deploys from an image."""

import asyncio
from pathlib import Path

import grpc
import pytest
from fastapi.testclient import TestClient

from app.deploys.repositories.deploys import Deploy
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route
from tests.fakes import (
    HOST_PORT,
    FakeAgentClients,
    FakeRoutes,
    make_worker,
    rpc_error,
    run_deploys,
)

BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}
OLD_IMAGE = "registry.local/blog@sha256:" + "b" * 64
OLD_DIGEST = "sha256:" + "b" * 64


@pytest.fixture(autouse=True)
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


def _add(uow: InMemoryDeploysUoW, deploy: Deploy) -> None:
    asyncio.run(uow.deploys.add(deploy))


def _running(
    deploy_id: str, status: str = "running", image: str = OLD_IMAGE, node: str = "node-a"
) -> Deploy:
    return Deploy(
        id=deploy_id,
        app_name="blog",
        status=status,  # pyright: ignore[reportArgumentType]
        commit_sha="c0ffee",
        image=image,
        node=node,
        host_port=30001,
    )


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


def _run_worker(uow, agents, routes) -> None:
    asyncio.run(run_deploys(make_worker(uow, agents, routes)))


# stop


def test_stop_removes_the_replica_marks_the_deploy_and_serves_the_stopped_page(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    tmp_path: Path,
):
    _add(deploys_uow, _running("d1"))
    agents.seed_replica("d1-r0", "blog")

    resp = client.post("/apps/blog/stop")

    assert resp.status_code == 204
    assert _get(deploys_uow, "d1").status == "stopped"
    assert client.get("/apps/blog").json()["replicas"] == 0
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d1-r0"}]
    assert routes.applied[-1] == []
    assert routes.applied_stopped[-1] == ["blog"]
    conf = (tmp_path / "routes" / "desired" / str(routes.last_gen) / "blog.conf").read_text()
    assert "server_name blog.bult.localhost;" in conf
    assert "snippets/stopped.conf" in conf
    assert "proxy_pass" not in conf


def test_stop_is_refused_while_a_deploy_is_in_progress(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="building"))

    resp = client.post("/apps/blog/stop")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_in_progress"
    assert client.get("/apps/blog").json()["replicas"] == 1
    assert agents.remove_calls == []


def test_a_normal_deploy_of_a_stopped_app_makes_it_wanted_again(client: TestClient):
    assert client.post("/apps/blog/stop").status_code == 204
    assert client.get("/apps/blog").json()["replicas"] == 0

    assert client.post("/apps/blog/deploys").status_code == 202

    assert client.get("/apps/blog").json()["replicas"] == 1


# start


def test_start_runs_the_last_image_without_a_build(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _add(deploys_uow, _running("d1"))
    agents.seed_replica("d1-r0", "blog")
    client.post("/apps/blog/stop")

    resp = client.post("/apps/blog/start")

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "starting"
    assert body["source_deploy_id"] == "d1"
    assert body["image"] == OLD_IMAGE
    assert client.get("/apps/blog").json()["replicas"] == 1

    _run_worker(deploys_uow, agents, routes)

    deploy = _get(deploys_uow, body["id"])
    assert deploy.status == "running"
    assert deploy.commit_sha == "c0ffee"
    assert agents.start_calls == []
    assert agents.get_calls == 0
    [call] = agents.run_calls
    assert call["image_digest"] == OLD_DIGEST
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", HOST_PORT)]
    assert routes.applied_stopped[-1] == []


def test_start_of_an_app_that_never_ran_says_to_deploy_first(
    client: TestClient, agents: FakeAgentClients
):
    resp = client.post("/apps/blog/start")

    assert resp.status_code == 409
    assert resp.json()["code"] == "nothing_to_start"
    assert "deploy the app first" in resp.json()["detail"]
    assert agents.run_calls == []


def test_start_ignores_a_deploy_that_never_ran(
    client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="failed", image=OLD_IMAGE))

    assert client.post("/apps/blog/start").json()["code"] == "nothing_to_start"


def test_start_of_a_running_app_is_a_conflict(
    client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    _add(deploys_uow, _running("d1"))

    resp = client.post("/apps/blog/start")

    assert resp.status_code == 409
    assert resp.json()["code"] == "app_already_running"


# rollback


def test_rollback_runs_the_chosen_image_without_a_build(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
):
    _add(deploys_uow, _running("d1", status="superseded"))
    _add(deploys_uow, _running("d2", image="registry.local/blog@sha256:" + "c" * 64))
    agents.seed_replica("d2-r0", "blog")

    resp = client.post("/apps/blog/deploys/d1/rollback")

    assert resp.status_code == 202
    body = resp.json()
    assert (body["status"], body["source_deploy_id"]) == ("starting", "d1")

    _run_worker(deploys_uow, agents, routes)

    assert agents.start_calls == []
    [call] = agents.run_calls
    assert call["image_digest"] == OLD_DIGEST
    assert _get(deploys_uow, body["id"]).status == "running"
    assert _get(deploys_uow, "d2").status == "superseded"
    assert list(agents.replicas["node-a"]) == [f"{body['id']}-r0"]


def test_rollback_of_a_deploy_that_never_ran_is_refused(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, Deploy(id="d1", app_name="blog", status="failed", image=OLD_IMAGE))
    _add(deploys_uow, Deploy(id="d2", app_name="blog", status="failed"))

    for deploy_id in ("d1", "d2"):  # failed before the route / before the build
        resp = client.post(f"/apps/blog/deploys/{deploy_id}/rollback")
        assert resp.status_code == 409
        assert resp.json()["code"] == "deploy_not_restorable"
    assert asyncio.run(deploys_uow.deploys.list_running("blog")) == []
    assert len(asyncio.run(deploys_uow.deploys.list_all())) == 2


def test_rollback_of_an_unknown_deploy_is_404(client: TestClient):
    resp = client.post("/apps/blog/deploys/nope/rollback")

    assert resp.status_code == 404
    assert resp.json()["code"] == "deploy_not_found"


def test_rollback_of_another_apps_deploy_is_404(
    client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    client.post("/apps", json={**BODY, "name": "shop"})
    _add(deploys_uow, Deploy(**{**_running("s1").__dict__, "app_name": "shop"}))

    assert client.post("/apps/blog/deploys/s1/rollback").status_code == 404


def test_rollback_while_a_deploy_is_active_is_409(
    client: TestClient, deploys_uow: InMemoryDeploysUoW
):
    _add(deploys_uow, _running("d1", status="superseded"))
    _add(deploys_uow, Deploy(id="d2", app_name="blog", status="queued"))

    resp = client.post("/apps/blog/deploys/d1/rollback")

    assert resp.status_code == 409
    assert resp.json()["code"] == "deploy_in_progress"


# logs


def test_logs_are_the_tail_of_the_running_replica(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, _running("d1"))
    agents.log_text = "one\ntwo\nthree\n"

    resp = client.get("/apps/blog/logs", params={"tail": 2})

    assert resp.status_code == 200
    assert resp.json() == {"deploy_id": "d1", "lines": ["two", "three"]}
    assert agents.log_calls == [
        {"node": "node-a", "replica_id": "d1-r0", "tail_lines": 2}
    ]


def test_logs_default_to_200_lines(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, _running("d1"))

    client.get("/apps/blog/logs")

    assert agents.log_calls[0]["tail_lines"] == 200


def test_logs_without_a_running_deploy_are_empty(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, _running("d1", status="superseded"))

    resp = client.get("/apps/blog/logs")

    assert resp.status_code == 200
    assert resp.json() == {"deploy_id": None, "lines": []}
    assert agents.log_calls == []


@pytest.mark.parametrize("tail", [0, -1, 1001, "many"])
def test_logs_tail_is_validated(client: TestClient, tail: int | str):
    resp = client.get("/apps/blog/logs", params={"tail": tail})

    assert resp.status_code == 422
    assert "tail" in resp.json()["fields"]


@pytest.mark.parametrize(
    "code, status, error_code",
    [
        (grpc.StatusCode.UNAVAILABLE, 503, "node_unavailable"),
        (grpc.StatusCode.DEADLINE_EXCEEDED, 503, "node_unavailable"),
        (grpc.StatusCode.INTERNAL, 500, "internal_error"),
    ],
)
def test_logs_grpc_errors_are_mapped(
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    code: grpc.StatusCode,
    status: int,
    error_code: str,
):
    _add(deploys_uow, _running("d1"))
    agents.log_error = rpc_error(code, "dial tcp 10.0.0.5:50051: refused")

    resp = client.get("/apps/blog/logs")

    assert resp.status_code == status
    assert resp.json()["code"] == error_code
    assert "10.0.0.5" not in resp.text


def test_logs_of_a_vanished_replica_are_empty(
    client: TestClient, deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _add(deploys_uow, _running("d1"))
    agents.log_error = rpc_error(grpc.StatusCode.NOT_FOUND)

    assert client.get("/apps/blog/logs").json() == {"deploy_id": "d1", "lines": []}
