"""Deploy saga tests: a worker on fakes drives claimed deploys through the steps."""

import asyncio

import grpc
import pytest

from app.deploys.repositories.deploys import Deploy
from app.deploys.services.runner import MAX_POLL_FAILURES
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route, RouteApplyError
from tests.fakes import (
    BUILD_ERROR,
    COMMIT_SHA,
    HOST_PORT,
    IMAGE_DIGEST,
    IMAGE_REPOSITORY,
    FakeAgentClients,
    FakeApps,
    FakeRoutes,
    make_worker,
    rpc_error,
    run_deploys,
)


def _uow_with_deploy(deploy_id: str) -> InMemoryDeploysUoW:
    uow = InMemoryDeploysUoW()
    asyncio.run(uow.deploys.add(Deploy(id=deploy_id, app_name="blog")))
    return uow


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


def _run(agents, uow, routes, apps: FakeApps | None = None):
    asyncio.run(run_deploys(make_worker(uow, agents, routes, apps=apps)))


def test_deploy_success(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=["RUNNING", "SUCCEEDED"])
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "running"
    assert deploy.node == "node-a"
    assert deploy.host_port == HOST_PORT
    assert deploy.commit_sha == COMMIT_SHA
    assert deploy.image == f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"
    assert deploy.error == ""
    assert deploy.attempts == 1

    [start] = agents.start_calls
    assert start["deploy_id"] == "d1"
    assert start["app_id"] == "blog"
    assert agents.get_calls == 2
    [call] = agents.run_calls
    assert call["replica_id"] == "d1-r0"
    assert call["image_digest"] == IMAGE_DIGEST
    assert call["env"] == {"PORT": "8000", "FORWARDED_ALLOW_IPS": "10.0.0.1"}

    # The route points at the node's IP (from RUNNERS), not at the node's name.
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", HOST_PORT)]


def test_build_failed(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=["FAILED"])
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == BUILD_ERROR
    assert agents.run_calls == []


def test_build_lost_when_builder_does_not_know_the_deploy(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=[rpc_error(grpc.StatusCode.NOT_FOUND)])
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build lost"
    assert agents.run_calls == []


def test_start_builder_unavailable(routes: FakeRoutes):
    agents = FakeAgentClients(start_error=rpc_error(grpc.StatusCode.UNAVAILABLE))
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build failed: builder unavailable, try again"
    assert agents.get_calls == 0


def test_start_invalid_argument_is_our_bug_and_stays_out_of_the_error(
    routes: FakeRoutes,
):
    secret = "invalid repo_url: /var/lib/bult/work/x"
    agents = FakeAgentClients(
        start_error=rpc_error(grpc.StatusCode.INVALID_ARGUMENT, secret)
    )
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build failed: internal error"
    assert "/var/lib" not in deploy.error


def test_start_deadline_retries_the_same_id(routes: FakeRoutes):
    agents = FakeAgentClients(
        start_error=rpc_error(grpc.StatusCode.DEADLINE_EXCEEDED),
        start_error_times=1,
        build_states=["SUCCEEDED"],
    )
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    assert [c["deploy_id"] for c in agents.start_calls] == ["d1", "d1"]
    assert _get(uow, "d1").status == "running"


def test_app_deleted_before_start_cancels_the_deploy(routes: FakeRoutes):
    agents = FakeAgentClients()
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes, apps=FakeApps(missing=True))

    assert agents.start_calls == []
    assert routes.applied == []


def test_run_replica_unavailable(routes: FakeRoutes):
    details = "dial tcp 192.168.252.6:50051: connection refused"
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"],
        run_error=rpc_error(grpc.StatusCode.UNAVAILABLE, details),
    )
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "start failed: node is unreachable"
    assert "192.168" not in deploy.error


def test_poll_survives_transient_unavailable(routes: FakeRoutes):
    agents = FakeAgentClients(
        build_states=["RUNNING", rpc_error(grpc.StatusCode.UNAVAILABLE), "SUCCEEDED"]
    )
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    assert _get(uow, "d1").status == "running"
    assert agents.get_calls == 3


def test_poll_gives_up_after_repeated_unavailable(routes: FakeRoutes):
    agents = FakeAgentClients(build_states=[rpc_error(grpc.StatusCode.UNAVAILABLE)])
    uow = _uow_with_deploy("d1")

    _run(agents, uow, routes)

    deploy = _get(uow, "d1")
    assert deploy.status == "failed"
    assert deploy.error == "build failed: node is unreachable"
    assert agents.get_calls == MAX_POLL_FAILURES
    assert agents.run_calls == []


def test_app_deleted_during_build(routes: FakeRoutes):
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(build_states=["SUCCEEDED"])
    # DELETE /apps/blog arrived after the claim, before the first write.
    original = agents.start_deploy

    async def start_then_delete(deploy_id: str, **kwargs):
        result = await original(deploy_id, **kwargs)
        await uow.deploys.delete_for_app("blog")
        return result

    agents.start_deploy = start_then_delete  # pyright: ignore[reportAttributeAccessIssue]

    _run(agents, uow, routes)

    assert agents.run_calls == []
    assert agents.remove_calls == []
    assert routes.applied == []


def test_app_deleted_after_run_replica_removes_replica(
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


def test_replica_removal_failure_is_only_logged(routes: FakeRoutes):
    uow = _uow_with_deploy("d1")
    agents = FakeAgentClients(
        build_states=["SUCCEEDED"],
        on_run=lambda: uow.deploys.delete_for_app("blog"),
        remove_error=rpc_error(grpc.StatusCode.UNAVAILABLE),
    )

    _run(agents, uow, routes)  # does not raise

    assert len(agents.remove_calls) == 1


def test_route_failure_fails_deploy_and_removes_replica(
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
