"""Deploy saga (run_deploy) tests: the background part, called directly."""

import asyncio

import grpc
import pytest

from app.deploys.repositories.deploys import Deploy
from app.deploys.services.runner import MAX_POLL_FAILURES, run_deploy
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route, RouteApplyError
from tests.fakes import (
    BUILD_ERROR,
    COMMIT_SHA,
    HOST_PORT,
    IMAGE_DIGEST,
    IMAGE_REPOSITORY,
    RUNNERS,
    TRUSTED_PROXY,
    FakeAgentClients,
    FakeRoutes,
    rpc_error,
)


def _uow_with_deploy(deploy_id: str) -> InMemoryDeploysUoW:
    uow = InMemoryDeploysUoW()
    asyncio.run(uow.deploys.add(Deploy(id=deploy_id, app_name="blog")))
    return uow


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


def test_run_deploy_success(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=["RUNNING", "SUCCEEDED"])
    uow = _uow_with_deploy("d1")

    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            "d1",
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )

    deploy = _get(uow, "d1")
    assert deploy.status == "running"
    assert deploy.node == "node-a"
    assert deploy.host_port == HOST_PORT
    assert deploy.commit_sha == COMMIT_SHA
    assert deploy.image == f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"
    assert deploy.error == ""

    assert agents.get_calls == 2
    [call] = agents.run_calls
    assert call["replica_id"] == "d1-r0"
    assert call["image_digest"] == IMAGE_DIGEST
    assert call["env"] == {"PORT": "8000", "FORWARDED_ALLOW_IPS": TRUSTED_PROXY}

    # The route points at the node's IP (from RUNNERS), not at the node's name.
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", HOST_PORT)]


def test_run_deploy_build_failed(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=["FAILED"])
    uow = _uow_with_deploy("d1")

    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            "d1",
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == BUILD_ERROR
    assert agents.run_calls == []


def test_run_deploy_run_replica_unavailable(routes: FakeRoutes):
    details = "dial tcp 192.168.252.6:50051: connection refused"
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"],
        run_error=rpc_error(grpc.StatusCode.UNAVAILABLE, details),
    )
    uow = _uow_with_deploy("d1")

    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            "d1",
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "start failed: node is unreachable"
    assert "192.168" not in deploy.error


def test_run_deploy_poll_survives_transient_unavailable(routes: FakeRoutes):
    agents = FakeAgentClients(
        build_states=["RUNNING", rpc_error(grpc.StatusCode.UNAVAILABLE), "SUCCEEDED"]
    )
    uow = _uow_with_deploy("d1")

    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            "d1",
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )

    assert _get(uow, "d1").status == "running"
    assert agents.get_calls == 3


def test_run_deploy_poll_gives_up_after_repeated_unavailable(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=[rpc_error(grpc.StatusCode.UNAVAILABLE)])
    uow = _uow_with_deploy("d1")

    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            "d1",
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build failed: node is unreachable"
    assert agents.get_calls == MAX_POLL_FAILURES
    assert agents.run_calls == []


def _run(agents, uow, routes, deploy_id="d1"):
    asyncio.run(
        run_deploy(
            agents,
            lambda: uow,
            routes,
            RUNNERS,
            deploy_id,
            "blog",
            TRUSTED_PROXY,
            poll_interval=0,
        )
    )


def test_run_deploy_app_deleted_during_build(routes: FakeRoutes):
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(build_states=["SUCCEEDED"])
    asyncio.run(
        uow.deploys.delete_for_app("blog")
    )  # DELETE /apps/blog arrived while the build ran

    _run(agents, uow, routes)

    assert agents.run_calls == []
    assert agents.remove_calls == []
    assert routes.applied == []


def test_run_deploy_app_deleted_after_run_replica_removes_replica(
    routes: FakeRoutes, caplog: pytest.LogCaptureFixture
):
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"], on_run=lambda: uow.deploys.delete_for_app("blog")
    )

    with caplog.at_level("INFO"):
        _run(agents, uow, routes)

    assert len(agents.run_calls) == 1
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d1-r0"}]
    assert routes.applied == []  # the deleted app's route is never published
    assert "deploy cancelled (app deleted)" in caplog.text


def test_run_deploy_replica_removal_failure_is_only_logged(routes: FakeRoutes):
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"],
        on_run=lambda: uow.deploys.delete_for_app("blog"),
        remove_error=rpc_error(grpc.StatusCode.UNAVAILABLE),
    )

    _run(agents, uow, routes)  # does not raise

    assert len(agents.remove_calls) == 1


def test_run_deploy_route_failure_fails_deploy_and_removes_replica(
    routes: FakeRoutes, monkeypatch: pytest.MonkeyPatch
):
    async def rejected(generation: int, timeout: float = 10.0) -> None:
        raise RouteApplyError("unexpected '}' in blog.conf")

    monkeypatch.setattr(routes, "wait_applied", rejected)
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(build_states=["SUCCEEDED"])

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "route failed: could not publish the app's address"
    assert "}" not in deploy.error  # nginx's message stays in the log
    assert agents.remove_calls == [{"node": "node-a", "replica_id": "d1-r0"}]
