"""Worker, lease, fencing, resume and the startup check, on fakes."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from app.agents.client import DeployResult
from app.apps.services.facade import AppsFacade
from app.deploys.repositories.deploys import Deploy
from app.deploys.services.reconcile import fail_deploys_without_replica
from app.deploys.uow import InMemoryDeploysUoW
from app.ingress.routes import Route
from tests.fakes import (
    HOST_PORT,
    IMAGE_DIGEST,
    IMAGE_REPOSITORY,
    RUNNERS,
    FakeAgentClients,
    FakeApps,
    FakeRoutes,
    make_worker,
    rpc_error,
    run_deploys,
)

LEASE = timedelta(seconds=30)
IMAGE = f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}"


def _now() -> datetime:
    return datetime.now(UTC)


async def _crashed_claims(uow: InMemoryDeploysUoW, times: int) -> None:
    """`times` workers claimed the deploy and died: each lease is long expired."""
    for i in range(times):
        at = _now() - timedelta(hours=1) + timedelta(minutes=i)  # each after the last lease
        claimed = await uow.deploys.claim(f"dead-{i}", LEASE, at)
        assert claimed is not None


async def _wait_until(condition, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not await condition():
            await asyncio.sleep(0.01)


def test_background_loop_takes_a_queued_deploy_to_running(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> None:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        agents.build_states = ["SUCCEEDED"]
        worker = make_worker(deploys_uow, agents, routes)
        worker.start()

        async def running() -> bool:
            deploy = await deploys_uow.deploys.get("d1")
            return deploy is not None and deploy.status == "running"

        try:
            await _wait_until(running)
        finally:
            await worker.stop()

    asyncio.run(scenario())
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", HOST_PORT)]


def test_gives_up_after_max_attempts(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        await _crashed_claims(deploys_uow, 3)  # attempts == 3: the 4th claim is too many
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert deploy is not None
    assert deploy.status == "failed"
    assert deploy.error == "gave up after 3 attempts"
    assert agents.start_calls == []


def test_a_deploy_with_attempts_left_is_still_processed(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        await _crashed_claims(deploys_uow, 2)
        agents.build_states = ["SUCCEEDED"]
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert deploy is not None
    assert deploy.status == "running"
    assert deploy.attempts == 3


def test_resume_starting_with_existing_replica_does_not_run_a_second_one(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(
            Deploy(id="d1", app_name="blog", status="starting", image=IMAGE)
        )
        await _crashed_claims(deploys_uow, 1)  # the old process died after RunReplica
        agents.seed_replica("d1-r0", "blog", port=40001)
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert agents.run_calls == []
    assert agents.start_calls == []
    assert deploy is not None
    assert deploy.status == "running"
    assert deploy.host_port == 40001
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", 40001)]


def test_resume_starting_without_replica_runs_it_once(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(
            Deploy(id="d1", app_name="blog", status="starting", image=IMAGE)
        )
        await _crashed_claims(deploys_uow, 1)
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    [call] = agents.run_calls
    assert call["replica_id"] == "d1-r0"
    assert call["image_repository"] == IMAGE_REPOSITORY
    assert call["image_digest"] == IMAGE_DIGEST
    assert deploy is not None
    assert deploy.status == "running"


def test_resume_building_polls_without_a_second_start_deploy(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(
            Deploy(id="d1", app_name="blog", status="building")
        )
        await _crashed_claims(deploys_uow, 1)
        agents.build_states = ["RUNNING", "SUCCEEDED"]
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert agents.start_calls == []
    assert deploy is not None
    assert deploy.status == "running"


def test_live_lease_is_not_taken_by_another_worker(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> int:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        await deploys_uow.deploys.claim("other", LEASE, _now())
        return await make_worker(deploys_uow, agents, routes).tick()

    assert asyncio.run(scenario()) == 0


def test_lease_taken_before_the_route_stops_the_old_worker_quietly(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def steal() -> None:
        await deploys_uow.deploys.claim("other", LEASE, _now() + timedelta(hours=1))

    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        agents.build_states = ["SUCCEEDED"]
        agents.on_run = steal  # the lease changes hands after RunReplica
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert deploy is not None
    assert deploy.status == "starting"
    assert deploy.lease_owner == "other"
    assert routes.applied == []
    assert agents.remove_calls == []  # the replica belongs to the new owner now


def test_fenced_write_after_route_wait_does_not_mark_running(
    deploys_uow: InMemoryDeploysUoW,
    agents: FakeAgentClients,
    routes: FakeRoutes,
    monkeypatch: pytest.MonkeyPatch,
):
    async def steal_while_waiting(generation: int, timeout: float = 10.0) -> None:
        await deploys_uow.deploys.claim("other", LEASE, _now() + timedelta(hours=1))

    monkeypatch.setattr(routes, "wait_applied", steal_while_waiting)

    async def scenario() -> Deploy | None:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        agents.build_states = ["SUCCEEDED"]
        await run_deploys(make_worker(deploys_uow, agents, routes))
        return await deploys_uow.deploys.get("d1")

    deploy = asyncio.run(scenario())

    assert deploy is not None
    assert deploy.status == "starting"  # the old worker's "running" was rejected
    assert deploy.lease_owner == "other"
    assert agents.remove_calls == []


def test_heartbeat_notices_the_lost_lease_and_stops_the_work(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    class SlowBuild(FakeAgentClients):
        async def get_deploy(self, deploy_id: str) -> DeployResult:
            if self.get_calls == 0:  # another worker takes over during the first poll
                await deploys_uow.deploys.claim(
                    "other", LEASE, _now() + timedelta(hours=1)
                )
            self.get_calls += 1
            await asyncio.sleep(0.01)
            return DeployResult(deploy_id=deploy_id, state="RUNNING")

    agents = SlowBuild()

    async def scenario() -> tuple[Deploy | None, bool]:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        worker = make_worker(deploys_uow, agents, routes, renew_every=0.02)
        await worker.tick()
        async with asyncio.timeout(2):
            await worker.join()  # returns only because the heartbeat cancelled the work
        return await deploys_uow.deploys.get("d1"), bool(worker._handlers)

    deploy, still_running = asyncio.run(scenario())

    assert not still_running
    assert deploy is not None
    assert deploy.status == "building"
    assert deploy.lease_owner == "other"
    assert agents.get_calls < 20  # polling stopped


def test_heartbeat_keeps_the_lease_alive(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    class SlowBuild(FakeAgentClients):
        async def get_deploy(self, deploy_id: str) -> DeployResult:
            self.get_calls += 1
            await asyncio.sleep(0.01)
            state = "SUCCEEDED" if self.get_calls > 15 else "RUNNING"
            return DeployResult(deploy_id=deploy_id, state=state)

    async def scenario() -> list[datetime | None]:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        worker = make_worker(
            deploys_uow, SlowBuild(), routes, renew_every=0.02, lease=timedelta(minutes=1)
        )
        await worker.tick()
        seen = []
        while worker._handlers:
            deploy = await deploys_uow.deploys.get("d1")
            assert deploy is not None
            if deploy.lease_until not in seen:
                seen.append(deploy.lease_until)
            await asyncio.sleep(0.01)
        return seen

    assert len(asyncio.run(scenario())) > 2  # lease_until kept moving forward


def test_graceful_stop_releases_the_lease_and_a_restart_claims_at_once(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    class EndlessBuild(FakeAgentClients):
        async def get_deploy(self, deploy_id: str) -> DeployResult:
            self.get_calls += 1
            await asyncio.sleep(0.01)
            return DeployResult(deploy_id=deploy_id, state="RUNNING")

    async def scenario() -> tuple[Deploy | None, Deploy | None]:
        await deploys_uow.deploys.add(Deploy(id="d1", app_name="blog"))
        first = make_worker(deploys_uow, EndlessBuild(), routes, worker_id="w1")
        await first.tick()
        await asyncio.sleep(0.05)  # in the middle of the build
        await first.stop()
        released = await deploys_uow.deploys.get("d1")

        second = make_worker(deploys_uow, FakeAgentClients(), routes, worker_id="w2")
        await second.tick()  # same clock, no waiting for the old lease to expire
        claimed = await deploys_uow.deploys.get("d1")
        await second.stop()
        return released, claimed

    released, claimed = asyncio.run(scenario())

    assert released is not None
    assert released.lease_until is None
    assert released.status == "building"
    assert released.attempts == 0  # a graceful stop is not a failed attempt
    assert claimed is not None
    assert claimed.lease_owner == "w2"


def test_concurrency_is_bounded(
    deploys_uow: InMemoryDeploysUoW, routes: FakeRoutes
):
    async def scenario() -> tuple[int, int]:
        for name in ("a", "b", "c"):
            await deploys_uow.deploys.add(Deploy(id=f"d-{name}", app_name=name))
        worker = make_worker(deploys_uow, FakeAgentClients(), routes, concurrency=2)
        first = await worker.tick()
        second = await worker.tick()  # both slots are busy
        await worker.stop()
        return first, second

    assert asyncio.run(scenario()) == (2, 0)


def _running(deploy_id: str, app_name: str, port: int, node: str = "node-a") -> Deploy:
    return Deploy(
        id=deploy_id, app_name=app_name, status="running", node=node, host_port=port
    )


def test_startup_check_fails_running_deploy_without_replica_and_drops_its_route(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    async def scenario() -> list[str]:
        await deploys_uow.deploys.add(_running("d-blog", "blog", 30001))
        await deploys_uow.deploys.add(_running("d-shop", "shop", 30002))
        agents.seed_replica("d-shop-r0", "shop", port=30002)  # blog's replica is gone
        return await fail_deploys_without_replica(
            agents, lambda: deploys_uow, routes, RUNNERS, cast(AppsFacade, FakeApps())
        )

    failed = asyncio.run(scenario())

    assert failed == ["d-blog"]
    blog = asyncio.run(deploys_uow.deploys.get("d-blog"))
    shop = asyncio.run(deploys_uow.deploys.get("d-shop"))
    assert blog is not None and blog.status == "failed"
    assert blog.error == "replica is gone"
    assert shop is not None and shop.status == "running"
    assert routes.applied[-1] == [Route("shop", "10.0.0.5", 30002)]


def test_startup_check_leaves_deploys_of_an_unreachable_node_alone(
    deploys_uow: InMemoryDeploysUoW, agents: FakeAgentClients, routes: FakeRoutes
):
    agents.list_error = rpc_error(__import__("grpc").StatusCode.UNAVAILABLE)

    async def scenario() -> list[str]:
        await deploys_uow.deploys.add(_running("d-blog", "blog", 30001))
        return await fail_deploys_without_replica(
            agents, lambda: deploys_uow, routes, RUNNERS, cast(AppsFacade, FakeApps())
        )

    assert asyncio.run(scenario()) == []
    blog = asyncio.run(deploys_uow.deploys.get("d-blog"))
    assert blog is not None and blog.status == "running"
    assert routes.applied[-1] == [Route("blog", "10.0.0.5", 30001)]
