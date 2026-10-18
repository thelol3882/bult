"""Redeploy pivot, garbage collection at startup, and the lease cleared by a final write."""

import asyncio

import grpc
import pytest

from app.deploys.repositories.deploys import Deploy
from app.deploys.services.reconcile import remove_orphan_replicas
from app.deploys.uow import InMemoryDeploysUoW
from tests.fakes import (
    HOST_PORT,
    IMAGE_DIGEST,
    IMAGE_REPOSITORY,
    FakeAgentClients,
    FakeRoutes,
    add_running_deploy,
    make_worker,
    one_route,
    rpc_error,
    run_deploys,
)

IMAGE = f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"


def _get(uow: InMemoryDeploysUoW, deploy_id: str) -> Deploy:
    deploy = asyncio.run(uow.deploys.get(deploy_id))
    assert deploy is not None
    return deploy


async def _redeploy(uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes, **kw):
    await add_running_deploy(uow, "old", "blog", [("node-a", 30001)], image=IMAGE)
    agents.seed_replica("old-r0", "blog", port=30001)
    await uow.deploys.add(Deploy(id="new", app_name="blog"))
    agents.build_states = ["SUCCEEDED"]
    await run_deploys(make_worker(uow, agents, routes, **kw))


def test_redeploy_supersedes_the_old_deploy_after_the_route_points_at_the_new_one(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    monkeypatch: pytest.MonkeyPatch,
):
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

    asyncio.run(_redeploy(deploys_uow, agents, routes))

    assert _get(deploys_uow, "new").status == "running"
    old = _get(deploys_uow, "old")
    assert old.status == "superseded"
    assert order == ["route", "remove old-r0"]
    assert list(agents.replicas["node-a"]) == ["new-r0"]
    assert routes.applied[-1] == [one_route("blog", "10.0.0.5", HOST_PORT)]


def test_failed_removal_of_the_old_replica_leaves_the_new_deploy_running(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    caplog: pytest.LogCaptureFixture,
):
    agents.remove_error = rpc_error(grpc.StatusCode.UNAVAILABLE)

    with caplog.at_level("WARNING"):
        asyncio.run(_redeploy(deploys_uow, agents, routes))

    assert _get(deploys_uow, "new").status == "running"
    assert _get(deploys_uow, "new").error == ""
    assert _get(deploys_uow, "old").status == "superseded"
    assert "could not remove replica old-r0" in caplog.text
    # The leftover is the garbage collector's job.
    assert "old-r0" in agents.replicas["node-a"]


def test_redeploy_does_not_touch_other_apps(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> None:
        await add_running_deploy(
            deploys_uow, "shop-1", "shop", [("node-a", 30002)], image=IMAGE
        )
        agents.seed_replica("shop-1-r0", "shop", port=30002)
        await _redeploy(deploys_uow, agents, routes)

    asyncio.run(scenario())

    assert _get(deploys_uow, "shop-1").status == "running"
    assert "shop-1-r0" in agents.replicas["node-a"]


def test_final_writes_clear_the_lease(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> None:
        await deploys_uow.deploys.add(Deploy(id="ok", app_name="blog"))
        await deploys_uow.deploys.add(Deploy(id="bad", app_name="shop"))
        agents.build_states = ["SUCCEEDED"]
        await run_deploys(make_worker(deploys_uow, agents, routes))
        broken = FakeAgentClients(build_states=["FAILED"])
        await deploys_uow.deploys.add(Deploy(id="bad2", app_name="docs"))
        await run_deploys(make_worker(deploys_uow, broken, routes))

    asyncio.run(scenario())

    for deploy_id, status in (("ok", "running"), ("bad2", "failed")):
        deploy = _get(deploys_uow, deploy_id)
        assert deploy.status == status
        assert (deploy.lease_owner, deploy.lease_until) == ("", None)


def test_superseded_deploy_has_no_lease_either(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    asyncio.run(_redeploy(deploys_uow, agents, routes))

    old = _get(deploys_uow, "old")
    assert (old.lease_owner, old.lease_until) == ("", None)


def test_slow_cleanup_after_the_final_write_is_not_cancelled_by_the_heartbeat(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    class SlowRemove(FakeAgentClients):
        async def remove_replica(self, node: str, replica_id: str) -> None:
            await asyncio.sleep(0.15)  # several heartbeats
            await super().remove_replica(node, replica_id)

    agents = SlowRemove()

    asyncio.run(_redeploy(deploys_uow, agents, routes, renew_every=0.02))

    assert "old-r0" not in agents.replicas["node-a"]


def _orphan_setup(uow: InMemoryDeploysUoW, agents: FakeAgentClients) -> None:
    async def add() -> None:
        await add_running_deploy(uow, "live", "blog", [("node-a", 30001)], image=IMAGE)
        await add_running_deploy(
            uow, "old", "blog", [("node-a", 30002)], image=IMAGE, status="superseded"
        )
        await add_running_deploy(
            uow, "halted", "blog", [("node-a", 30003)], image=IMAGE, status="stopped"
        )
        await uow.deploys.add(Deploy(id="busy", app_name="shop", status="starting"))

    asyncio.run(add())
    for replica_id in ("live-r0", "old-r0", "halted-r0", "busy-r0", "ghost-r0"):
        agents.seed_replica(replica_id, "blog")


def test_garbage_collection_removes_replicas_of_deploys_that_are_not_running(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _orphan_setup(deploys_uow, agents)

    removed = asyncio.run(remove_orphan_replicas(agents, lambda: deploys_uow))

    assert sorted(r for _, r in removed) == ["ghost-r0", "halted-r0", "old-r0"]
    # Kept: the running deploy's replica and the one a deploy in flight will reuse.
    assert sorted(agents.replicas["node-a"]) == ["busy-r0", "live-r0"]


def test_garbage_collection_skips_a_node_that_does_not_answer(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    _orphan_setup(deploys_uow, agents)
    agents.list_error = rpc_error(grpc.StatusCode.UNAVAILABLE)

    removed = asyncio.run(remove_orphan_replicas(agents, lambda: deploys_uow))

    assert removed == []
    assert agents.remove_calls == []


def test_garbage_collection_ignores_replicas_it_does_not_recognise(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients
):
    agents.seed_replica("hand-made", "blog")

    removed = asyncio.run(remove_orphan_replicas(agents, lambda: deploys_uow))

    assert removed == []
    assert "hand-made" in agents.replicas["node-a"]
