"""Queue semantics of the in-memory DeployRepository (the SQL one is tested on PostgreSQL)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.deploys.errors import DeployInProgressError
from app.deploys.repositories.deploys import Deploy, InMemoryDeployRepository

LEASE = timedelta(seconds=30)
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _repo(*deploys: Deploy) -> InMemoryDeployRepository:
    repo = InMemoryDeployRepository()

    async def seed() -> None:
        for deploy in deploys:
            await repo.add(deploy)

    asyncio.run(seed())
    return repo


def test_second_active_deploy_of_an_app_is_rejected():
    repo = _repo(Deploy(id="d1", app_name="blog"))

    with pytest.raises(DeployInProgressError):
        asyncio.run(repo.add(Deploy(id="d2", app_name="blog")))

    asyncio.run(repo.add(Deploy(id="d3", app_name="shop")))  # another app is fine


@pytest.mark.parametrize("status", ["running", "failed"])
def test_new_deploy_is_allowed_after_a_finished_one(status: str):
    repo = _repo(Deploy(id="d1", app_name="blog", status=status))  # pyright: ignore[reportArgumentType]

    asyncio.run(repo.add(Deploy(id="d2", app_name="blog")))


def test_claim_takes_the_oldest_unleased_active_deploy():
    repo = _repo(
        Deploy(id="d-run", app_name="a", status="running"),
        Deploy(id="d-old", app_name="b"),
        Deploy(id="d-new", app_name="c"),
    )

    first = asyncio.run(repo.claim("w1", LEASE, NOW))
    second = asyncio.run(repo.claim("w2", LEASE, NOW))
    third = asyncio.run(repo.claim("w3", LEASE, NOW))

    assert first is not None and first.id == "d-old"
    assert first.lease_owner == "w1"
    assert first.lease_until == NOW + LEASE
    assert first.attempts == 1
    assert second is not None and second.id == "d-new"
    assert third is None  # a running deploy is not work


def test_claim_skips_a_live_lease_and_takes_an_expired_one():
    repo = _repo(Deploy(id="d1", app_name="blog"))
    asyncio.run(repo.claim("w1", LEASE, NOW))

    assert asyncio.run(repo.claim("w2", LEASE, NOW + LEASE - timedelta(seconds=1))) is None

    stolen = asyncio.run(repo.claim("w2", LEASE, NOW + LEASE + timedelta(seconds=1)))
    assert stolen is not None
    assert stolen.lease_owner == "w2"
    assert stolen.attempts == 2


def test_renew_only_for_the_lease_holder():
    repo = _repo(Deploy(id="d1", app_name="blog"))
    asyncio.run(repo.claim("w1", LEASE, NOW))

    assert asyncio.run(repo.renew("d1", "w2", LEASE, NOW + LEASE)) is False
    assert asyncio.run(repo.renew("nope", "w1", LEASE, NOW)) is False
    assert asyncio.run(repo.renew("d1", "w1", LEASE, NOW + timedelta(seconds=10))) is True

    deploy = asyncio.run(repo.get("d1"))
    assert deploy is not None
    assert deploy.lease_until == NOW + timedelta(seconds=10) + LEASE


def test_update_owned_is_fenced_by_the_lease_owner():
    repo = _repo(Deploy(id="d1", app_name="blog"))
    asyncio.run(repo.claim("w1", LEASE, NOW))

    assert asyncio.run(repo.update_owned("d1", "w2", status="running")) is None
    stored = asyncio.run(repo.get("d1"))
    assert stored is not None and stored.status == "queued"

    changed = asyncio.run(repo.update_owned("d1", "w1", status="building"))
    assert changed is not None and changed.status == "building"
    assert asyncio.run(repo.update_owned("nope", "w1", status="building")) is None


def test_update_cannot_touch_lease_fields_but_the_owner_can_release():
    repo = _repo(Deploy(id="d1", app_name="blog"))
    asyncio.run(repo.claim("w1", LEASE, NOW))

    with pytest.raises(TypeError):
        asyncio.run(repo.update("d1", lease_owner="w2"))

    released = asyncio.run(repo.update_owned("d1", "w1", lease_until=None, attempts=0))
    assert released is not None and released.lease_until is None

    # A final write clears the owner too; after that the old owner is fenced out.
    cleared = asyncio.run(repo.update_owned("d1", "w1", lease_owner="", status="running"))
    assert cleared is not None and cleared.lease_owner == ""
    assert asyncio.run(repo.update_owned("d1", "w1", status="failed")) is None
