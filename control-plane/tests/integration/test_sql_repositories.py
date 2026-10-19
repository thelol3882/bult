"""Integration tests on real PostgreSQL (docker compose up -d postgres)."""

import asyncio
import functools
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.apps.errors import AppNameTakenError
from app.apps.repositories.apps import App, AppRoute
from app.apps.uow import SqlAppsUoW
from app.auth.errors import EmailTakenError
from app.auth.repositories.users import User
from app.auth.uow import SqlAuthUoW
from app.core.db import create_engine, create_session_factory
from app.deploys.errors import DeployInProgressError
from app.deploys.repositories.deploys import Deploy
from app.deploys.repositories.replicas import Replica
from app.nodes.repositories.nodes import Node
from app.nodes.uow import SqlNodesUoW
from app.deploys.uow import SqlDeploysUoW

pytestmark = pytest.mark.integration


def db_test(
    test: Callable[[async_sessionmaker], Coroutine[Any, Any, None]],
) -> Callable[[str], None]:
    """Run an async test in its own loop (no pytest-asyncio) on a migrated, empty DB."""

    @functools.wraps(test)
    def wrapper(database_url: str) -> None:
        async def main() -> None:
            engine = create_engine(database_url)
            try:
                await test(create_session_factory(engine))
            finally:
                await engine.dispose()

        asyncio.run(main())

    del wrapper.__wrapped__  # pytest must see `database_url`, not `factory`
    return wrapper


async def make_user(factory: async_sessionmaker, email: str = "owner@example.com") -> UUID:
    async with SqlAuthUoW(factory) as uow:
        user = await uow.users.add(User(email=email, password_hash="hash"))
        await uow.commit()
    assert user.id is not None
    return user.id


def make_app(owner_id: UUID, name: str = "hello") -> App:
    return App(
        owner_id=owner_id,
        name=name,
        preset="fastapi",
        repo_url="https://github.com/thelol3882/bult",
        branch="main",
        subdir="examples/fastapi-html",
    )


async def read_timestamps(
    factory: async_sessionmaker, deploy_id: str
) -> tuple[datetime, datetime]:
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT created_at, updated_at FROM deploys WHERE id = :i"),
                {"i": deploy_id},
            )
        ).one()
        return row.created_at, row.updated_at


@db_test
async def test_app_repository_roundtrip(factory: async_sessionmaker):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        added = await uow.apps.add(make_app(owner, "hello"))
        await uow.apps.add(make_app(owner, "alpha"))
        await uow.commit()

    assert isinstance(added.id, UUID)
    assert isinstance(added.created_at, datetime)

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.get("hello") == added
        assert await uow.apps.get("missing") is None
        assert [a.name for a in await uow.apps.list(owner, 0, 100)] == ["alpha", "hello"]
        assert await uow.apps.delete("hello") is True
        assert await uow.apps.delete("hello") is False
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        assert [a.name for a in await uow.apps.list(owner, 0, 100)] == ["alpha"]


@db_test
async def test_duplicate_name_is_app_name_taken(factory: async_sessionmaker):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        with pytest.raises(AppNameTakenError):
            await uow.apps.add(make_app(owner))


@db_test
async def test_deleting_app_cascades_to_deploys(factory: async_sessionmaker):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))
        await uow.commit()
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.add(Deploy(id="d1", app_name="hello"))
        await uow.commit()

    # Only the apps repository is touched: the rows go away through the FK.
    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.delete("hello") is True
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.list_all() == []


@db_test
async def test_uow_without_commit_saves_nothing(factory: async_sessionmaker):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.list(owner, 0, 100) == []


@db_test
async def test_update_missing_deploy_returns_none(factory: async_sessionmaker):
    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.update("nope", status="running") is None


@db_test
async def test_update_bumps_updated_at_but_not_created_at(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))
        await uow.commit()
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.add(Deploy(id="d1", app_name="hello"))
        await uow.commit()
    created, updated = await read_timestamps(factory, "d1")

    async with SqlDeploysUoW(factory) as uow:
        changed = await uow.deploys.update("d1", status="running", ran=True)
        await uow.commit()
    assert changed is not None
    assert changed.status == "running"
    assert changed.ran

    created_after, updated_after = await read_timestamps(factory, "d1")
    assert created_after == created
    assert updated_after > updated


@db_test
async def test_cursor_pages_with_equal_created_at_have_no_gaps_or_duplicates(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))
        await uow.commit()
    # Three deploys share one timestamp: only (created_at, id) orders them uniquely.
    older = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    newer = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    rows = [("d1", older), ("d2", older), ("d3", older), ("d4", newer), ("d5", newer)]
    async with factory() as session:
        for deploy_id, created_at in rows:
            await session.execute(
                text("INSERT INTO deploys (id, app_name, status, created_at)"
                    " VALUES (:i, 'hello', 'running', :c)"),
                {"i": deploy_id, "c": created_at},
            )
        await session.commit()

    seen: list[str] = []
    before = None
    while True:
        async with SqlDeploysUoW(factory) as uow:
            page = await uow.deploys.list_for_app("hello", before, 2)
        if not page:
            break
        seen += [d.id for d in page]
        last = page[-1]
        assert last.created_at is not None
        before = (last.created_at, last.id)

    assert seen == ["d5", "d4", "d3", "d2", "d1"]


@db_test
async def test_user_repository_roundtrip(factory: async_sessionmaker):
    async with SqlAuthUoW(factory) as uow:
        added = await uow.users.add(User(email="a@example.com", password_hash="h1"))
        await uow.commit()

    assert isinstance(added.id, UUID)
    assert isinstance(added.created_at, datetime)
    async with SqlAuthUoW(factory) as uow:
        assert await uow.users.get_by_email("a@example.com") == added
        assert await uow.users.get(added.id) == added
        assert await uow.users.get_by_email("b@example.com") is None
        assert await uow.users.get(UUID(int=0)) is None


@db_test
async def test_duplicate_email_is_email_taken(factory: async_sessionmaker):
    await make_user(factory, "a@example.com")

    async with SqlAuthUoW(factory) as uow:
        with pytest.raises(EmailTakenError):
            await uow.users.add(User(email="a@example.com", password_hash="h2"))


@db_test
async def test_set_password_hash(factory: async_sessionmaker):
    user_id = await make_user(factory)

    async with SqlAuthUoW(factory) as uow:
        await uow.users.set_password_hash(user_id, "new-hash")
        await uow.commit()

    async with SqlAuthUoW(factory) as uow:
        user = await uow.users.get(user_id)
    assert user is not None
    assert user.password_hash == "new-hash"


@db_test
async def test_apps_list_and_count_are_filtered_by_owner(factory: async_sessionmaker):
    alice = await make_user(factory, "alice@example.com")
    bob = await make_user(factory, "bob@example.com")
    async with SqlAppsUoW(factory) as uow:
        for name in ("b-app", "a-app"):
            await uow.apps.add(make_app(alice, name))
        await uow.apps.add(make_app(bob, "bobs"))
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.count(alice) == 2
        assert [a.name for a in await uow.apps.list(alice, 0, 100)] == ["a-app", "b-app"]
        assert [a.name for a in await uow.apps.list(alice, 1, 100)] == ["b-app"]
        assert await uow.apps.count(bob) == 1
        assert [a.name for a in await uow.apps.list(bob, 0, 100)] == ["bobs"]
        assert (await uow.apps.get("bobs")).owner_id == bob  # pyright: ignore[reportOptionalMemberAccess]


@db_test
async def test_deleting_a_user_who_owns_an_app_is_restricted(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner))
        await uow.commit()

    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text("DELETE FROM users WHERE id = :i"), {"i": owner})


LEASE = timedelta(seconds=30)


async def make_app_named(factory: async_sessionmaker, name: str, owner: UUID) -> None:
    async with SqlAppsUoW(factory) as uow:
        await uow.apps.add(make_app(owner, name))
        await uow.commit()


async def add_deploy(factory: async_sessionmaker, deploy: Deploy) -> None:
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.add(deploy)
        await uow.commit()


@db_test
async def test_second_active_deploy_violates_the_partial_unique_index(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await make_app_named(factory, "other", owner)
    insert = text("INSERT INTO deploys (id, app_name, status) VALUES (:i, :a, :s)")

    async def raw_insert(deploy_id: str, app: str, status: str) -> None:
        async with factory() as session:
            await session.execute(insert, {"i": deploy_id, "a": app, "s": status})
            await session.commit()

    await raw_insert("d1", "hello", "queued")
    await raw_insert("d-other", "other", "queued")  # another app is fine
    for status in ("queued", "building", "starting"):
        with pytest.raises(IntegrityError):
            await raw_insert("d2", "hello", status)

    # Finished deploys are not work: any number of them, and a new active one after.
    async with factory() as session:
        await session.execute(text("UPDATE deploys SET status = 'running' WHERE id = 'd1'"))
        await session.commit()
    await raw_insert("d3", "hello", "failed")
    await raw_insert("d4", "hello", "queued")


@db_test
async def test_second_active_deploy_is_deploy_in_progress(factory: async_sessionmaker):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await add_deploy(factory, Deploy(id="d1", app_name="hello"))

    with pytest.raises(DeployInProgressError):
        await add_deploy(factory, Deploy(id="d2", app_name="hello"))

    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.update("d1", status="running")
        await uow.commit()
    await add_deploy(factory, Deploy(id="d3", app_name="hello"))


@db_test
async def test_concurrent_claims_never_return_the_same_deploy(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    names = [f"app{i}" for i in range(6)]
    for name in names:
        await make_app_named(factory, name, owner)
        await add_deploy(factory, Deploy(id=f"d-{name}", app_name=name))
    now = datetime.now(UTC)

    async def claim(worker: str) -> Deploy | None:
        async with SqlDeploysUoW(factory) as uow:
            deploy = await uow.deploys.claim(worker, LEASE, now)
            await asyncio.sleep(0.05)  # keep the row lock while the others try
            await uow.commit()
            return deploy

    claimed = await asyncio.gather(*(claim(f"w{i}") for i in range(4)))

    ids = [d.id for d in claimed if d is not None]
    assert len(ids) == 4
    assert len(set(ids)) == 4  # SKIP LOCKED: nobody got a row another claim held
    assert {d.attempts for d in claimed if d is not None} == {1}


@db_test
async def test_claim_order_expiry_and_attempts(factory: async_sessionmaker):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await make_app_named(factory, "other", owner)
    await add_deploy(factory, Deploy(id="d-old", app_name="hello"))
    await add_deploy(factory, Deploy(id="d-new", app_name="other"))
    now = datetime.now(UTC)

    async def claim(worker: str, at: datetime) -> Deploy | None:
        async with SqlDeploysUoW(factory) as uow:
            deploy = await uow.deploys.claim(worker, LEASE, at)
            await uow.commit()
            return deploy

    first = await claim("w1", now)
    second = await claim("w2", now)
    assert first is not None and first.id == "d-old"
    assert first.lease_owner == "w1"
    assert first.lease_until is not None
    assert second is not None and second.id == "d-new"
    assert await claim("w3", now) is None  # both leases are alive

    again = await claim("w3", now + LEASE + timedelta(seconds=1))
    assert again is not None and again.id == "d-old"
    assert again.attempts == 2
    assert again.lease_owner == "w3"


@db_test
async def test_renew_and_update_owned_ignore_a_wrong_owner(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await add_deploy(factory, Deploy(id="d1", app_name="hello"))
    now = datetime.now(UTC)
    async with SqlDeploysUoW(factory) as uow:
        claimed = await uow.deploys.claim("w1", LEASE, now)
        await uow.commit()
    assert claimed is not None and claimed.lease_until is not None

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.renew("d1", "w2", LEASE, now + LEASE) is False
        assert await uow.deploys.update_owned("d1", "w2", status="running") is None
        assert await uow.deploys.update_owned("nope", "w1", status="running") is None
        await uow.commit()
    async with SqlDeploysUoW(factory) as uow:
        unchanged = await uow.deploys.get("d1")
    assert unchanged is not None
    assert unchanged.status == "queued"
    assert unchanged.lease_until == claimed.lease_until

    async with SqlDeploysUoW(factory) as uow:
        later = now + timedelta(seconds=10)
        assert await uow.deploys.renew("d1", "w1", LEASE, later) is True
        changed = await uow.deploys.update_owned("d1", "w1", status="building")
        await uow.commit()
    assert changed is not None and changed.status == "building"
    assert changed.lease_until == later + LEASE

    async with SqlDeploysUoW(factory) as uow:
        released = await uow.deploys.update_owned(
            "d1", "w1", lease_until=None, attempts=0
        )
        await uow.commit()
    assert released is not None
    assert released.lease_until is None
    assert released.attempts == 0


@db_test
async def test_app_env_and_replicas_roundtrip_and_list_stopped(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    await make_app_named(factory, "alpha", owner)
    await make_app_named(factory, "beta", owner)

    async with SqlAppsUoW(factory) as uow:
        fresh = await uow.apps.get("alpha")
        assert fresh is not None
        assert fresh.replicas == 1
        assert fresh.env == {}

        assert await uow.apps.list_stopped() == []
        await uow.apps.update("beta", replicas=0, env={"API_KEY": "s3cret"})
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        beta = await uow.apps.get("beta")
        assert beta is not None
        assert (beta.replicas, beta.env) == (0, {"API_KEY": "s3cret"})
        assert await uow.apps.list_stopped() == ["beta"]
        assert "s3cret" not in repr(beta)


@db_test
async def test_app_routes_roundtrip_list_and_removal(factory: async_sessionmaker):
    owner = await make_user(factory)
    for name in ("shop", "shop-api", "shop-img", "blog"):
        await make_app_named(factory, name, owner)

    async with SqlAppsUoW(factory) as uow:
        shop = await uow.apps.get("shop")
        assert shop is not None and shop.routes == ()
        assert await uow.apps.list_routes() == {}
        updated = await uow.apps.set_routes(
            "shop", (AppRoute("/api", "shop-api"), AppRoute("/img", "shop-img"))
        )
        assert updated is not None and len(updated.routes) == 2
        await uow.apps.set_routes("blog", (AppRoute("/api", "shop-api"),))
        assert await uow.apps.set_routes("ghost", ()) is None
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.list_routes() == {
            "shop": (AppRoute("/api", "shop-api"), AppRoute("/img", "shop-img")),
            "blog": (AppRoute("/api", "shop-api"),),
        }
        await uow.apps.remove_routes_to("shop-api")
        await uow.commit()

    async with SqlAppsUoW(factory) as uow:
        assert await uow.apps.list_routes() == {"shop": (AppRoute("/img", "shop-img"),)}


@db_test
async def test_running_and_restorable_queries(factory: async_sessionmaker):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await make_app_named(factory, "other", owner)
    image = "registry/hello@sha256:" + "a" * 64
    ran = {"image": image, "ran": True}

    # Oldest to newest: a replaced deploy, one that never ran, the running one, another app's.
    await add_deploy(factory, Deploy(id="d1", app_name="hello", status="superseded", **ran))
    await add_deploy(
        factory, Deploy(id="d2", app_name="hello", status="failed", image=image)
    )
    await add_deploy(factory, Deploy(id="d3", app_name="hello", status="running", **ran))
    await add_deploy(factory, Deploy(id="d4", app_name="other", status="running", **ran))

    async with SqlDeploysUoW(factory) as uow:
        assert [d.id for d in await uow.deploys.list_running("hello")] == ["d3"]
        newest = await uow.deploys.latest_restorable("hello")
        assert newest is not None and newest.id == "d3"
        assert await uow.deploys.update("d3", status="stopped") is not None
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.list_running("hello") == []
        stopped = await uow.deploys.latest_restorable("hello")
        assert stopped is not None and stopped.id == "d3"  # d2 never ran
        assert await uow.deploys.latest_restorable("nobody") is None


@db_test
async def test_deploy_from_image_stores_its_source_and_a_final_write_clears_the_lease(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await add_deploy(
        factory,
        Deploy(
            id="d2",
            app_name="hello",
            status="starting",
            image="registry/hello@sha256:" + "a" * 64,
            source_deploy_id="d1",
        ),
    )
    now = datetime.now(UTC)
    async with SqlDeploysUoW(factory) as uow:
        claimed = await uow.deploys.claim("w1", LEASE, now)
        await uow.commit()
    assert claimed is not None
    assert (claimed.status, claimed.source_deploy_id) == ("starting", "d1")
    assert claimed.lease_owner == "w1"

    async with SqlDeploysUoW(factory) as uow:
        done = await uow.deploys.update_owned(
            "d2", "w1", status="running", lease_owner="", lease_until=None
        )
        await uow.commit()
        assert done is not None
        assert (done.lease_owner, done.lease_until) == ("", None)
        assert await uow.deploys.update_owned("d2", "w1", status="failed") is None


@db_test
async def test_cancel_queued_respects_status_and_live_lease(
    factory: async_sessionmaker,
):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await add_deploy(factory, Deploy(id="d1", app_name="hello"))
    now = datetime.now(UTC)
    async with SqlDeploysUoW(factory) as uow:
        await uow.deploys.claim("w1", LEASE, now)
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.cancel_queued("d1", now) is None  # lease is alive
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        cancelled = await uow.deploys.cancel_queued("d1", now + LEASE + timedelta(seconds=1))
        await uow.commit()
    assert cancelled is not None
    assert (cancelled.status, cancelled.lease_owner, cancelled.lease_until) == ("cancelled", "", None)

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.deploys.cancel_queued("d1", now) is None  # no longer queued
        assert await uow.deploys.claim("w2", LEASE, now) is None  # and not work any more


@db_test
async def test_replicas_roundtrip_counts_and_cascade(factory: async_sessionmaker):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)
    await add_deploy(factory, Deploy(id="d1", app_name="hello", desired_replicas=3))

    async with SqlDeploysUoW(factory) as uow:
        for index, node in enumerate(["node-a", "node-b", "node-a"]):
            assert await uow.replicas.save(
                Replica(f"d1-r{index}", "d1", index, node, 20000 + index)
            )
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert [r.index for r in await uow.replicas.list_running(["d1"])] == [0, 1, 2]
        assert await uow.replicas.count_running_by_node() == {"node-a": 2, "node-b": 1}
        await uow.replicas.mark_removed(["d1-r1"])
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert [r.id for r in await uow.replicas.list_all_running()] == ["d1-r0", "d1-r2"]
        assert await uow.replicas.count_running_by_node() == {"node-a": 2}
        # Saving again is an upsert: a replica found on another node moves, and comes back.
        assert await uow.replicas.save(Replica("d1-r1", "d1", 1, "node-c", 20009))
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        moved = [r for r in await uow.replicas.list_running(["d1"]) if r.index == 1]
        assert [(r.node, r.host_port) for r in moved] == [("node-c", 20009)]
        await uow.deploys.delete_for_app("hello")
        await uow.commit()

    async with SqlDeploysUoW(factory) as uow:
        assert await uow.replicas.list_all_running() == []  # the deploy took them along


@db_test
async def test_saving_a_replica_of_a_vanished_deploy_returns_false(
    factory: async_sessionmaker,
):
    async with SqlDeploysUoW(factory) as uow:
        assert not await uow.replicas.save(Replica("ghost-r0", "ghost", 0, "node-a", 1))


@db_test
async def test_node_upsert_keeps_created_at_and_replaces_the_rest(
    factory: async_sessionmaker,
):
    first_seen = datetime.now(UTC) - timedelta(minutes=5)
    async with SqlNodesUoW(factory) as uow:
        first = await uow.nodes.upsert(
            Node("node-a", "10.0.0.5:50051", "runner", first_seen, "v1", 2, 1 << 31)
        )
        await uow.commit()
    assert first.created_at is not None

    async with SqlNodesUoW(factory) as uow:
        again = await uow.nodes.upsert(
            Node("node-a", "10.0.0.9:50051", "both", datetime.now(UTC), "v2", 4, 1 << 32)
        )
        await uow.commit()

    async with SqlNodesUoW(factory) as uow:
        [node] = await uow.nodes.list()
    assert node.address == "10.0.0.9:50051"
    assert (node.role, node.version, node.cpus, node.memory_bytes) == ("both", "v2", 4, 1 << 32)
    assert node.last_seen_at > first_seen
    assert node.created_at == first.created_at == again.created_at


@db_test
async def test_apps_replicas_are_limited_to_zero_to_five(factory: async_sessionmaker):
    owner = await make_user(factory)
    await make_app_named(factory, "hello", owner)

    async with SqlAppsUoW(factory) as uow:
        with pytest.raises(IntegrityError):
            await uow.apps.update("hello", replicas=6)
