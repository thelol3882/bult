"""Replica metrics: stored from heartbeats, kept for the retention, shaped for charts."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.deploys.uow import InMemoryDeploysUoW
from app.metrics.repositories.metrics import BUCKET_ORIGIN, ReplicaSample
from app.metrics.services import metrics as metrics_module
from app.metrics.services.metrics import (
    MAX_POINTS,
    MetricsService,
    bucket_seconds,
    replica_index,
)
from app.metrics.uow import InMemoryMetricsUoW
from tests.fakes import (
    NODE_B,
    NODE_TOKENS,
    FakeClock,
    FakeNodes,
    add_running_deploy,
)

HEARTBEAT = "/internal/nodes/heartbeat"
BODY = {
    "name": "blog",
    "preset": "fastapi",
    "repo_url": "https://github.com/example/blog.git",
}


def _beat(node: str = "node-a", replicas: list[dict] | None = None) -> dict:
    body: dict[str, object] = {"name": node, "address": "10.0.0.5:50051", "role": "runner"}
    if replicas is not None:
        body["replicas"] = replicas
    return body


def _usage(replica_id: str, cpu_pct: float = 50.0, mem: int = 100) -> dict:
    return {
        "replica_id": replica_id,
        "cpu_cores": cpu_pct / 100,
        "cpu_limit_pct": cpu_pct,
        "mem_bytes": mem,
        "mem_limit_bytes": 1000,
    }


def _post(client: TestClient, node: str, body: dict):
    return client.post(
        HEARTBEAT, json=body, headers={"Authorization": f"Bearer {NODE_TOKENS[node]}"}
    )


def _sample(clock: FakeClock, replica_id: str, ago: float, cpu: float = 10.0, mem: int = 100, node: str = "node-a") -> ReplicaSample:
    return ReplicaSample(
        replica_id=replica_id,
        app_name="blog",
        node=node,
        ts=clock.now - timedelta(seconds=ago),
        cpu_cores=cpu / 100,
        cpu_limit_pct=cpu,
        mem_bytes=mem,
        mem_limit_bytes=1000,
    )


def _store(uow: InMemoryMetricsUoW, *samples: ReplicaSample) -> None:
    asyncio.run(uow.metrics.add_many(samples))


def _running(deploys_uow: InMemoryDeploysUoW, placements=None) -> None:
    asyncio.run(add_running_deploy(deploys_uow, "d1", "blog", placements))


@pytest.fixture
def blog(client: TestClient) -> None:
    assert client.post("/apps", json=BODY).status_code == 201


# --- storing from heartbeats ---


def test_heartbeat_stores_samples_of_known_replicas_and_ignores_the_rest(
    blog: None,
    anon_client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    metrics_uow: InMemoryMetricsUoW,
    clock: FakeClock,
):
    _running(deploys_uow, [("node-a", 30001), ("node-a", 30002)])

    resp = _post(
        anon_client,
        "node-a",
        _beat(replicas=[_usage("d1-r0", 40, 111), _usage("d1-r1"), _usage("ghost-r0")]),
    )

    assert resp.status_code == 204
    stored = {s.replica_id: s for s in metrics_uow.samples}
    assert set(stored) == {"d1-r0", "d1-r1"}
    first = stored["d1-r0"]
    assert (first.app_name, first.node, first.ts) == ("blog", "node-a", clock.now)
    assert (first.cpu_limit_pct, first.mem_bytes, first.mem_limit_bytes) == (40, 111, 1000)


def test_heartbeat_without_the_replicas_field_is_still_accepted(
    anon_client: TestClient, metrics_uow: InMemoryMetricsUoW
):
    assert _post(anon_client, "node-a", _beat()).status_code == 204
    assert metrics_uow.samples == []


def test_a_node_cannot_report_replicas_that_run_elsewhere(
    blog: None,
    anon_client: TestClient,
    nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    metrics_uow: InMemoryMetricsUoW,
):
    nodes.add(*NODE_B)
    _running(deploys_uow, [("node-a", 30001)])

    assert _post(anon_client, "node-b", _beat("node-b", [_usage("d1-r0")])).status_code == 204

    assert metrics_uow.samples == []


def test_a_failing_metrics_store_does_not_fail_the_heartbeat(
    app, anon_client: TestClient, nodes_uow
):
    async def broken(node, usage):
        raise RuntimeError("database is down")

    app.state.usage_sink = broken

    assert _post(anon_client, "node-a", _beat(replicas=[_usage("d1-r0")])).status_code == 204
    assert [n.name for n in asyncio.run(nodes_uow.nodes.list())] == ["node-a"]  # liveness recorded


@pytest.mark.parametrize(
    "bad",
    [
        {**_usage("d1-r0"), "cpu_limit_pct": -1},
        {**_usage("d1-r0"), "mem_bytes": -5},
        {**_usage("d1-r0"), "extra": 1},
        {"replica_id": "d1-r0"},
    ],
)
def test_malformed_usage_is_rejected(anon_client: TestClient, bad: dict):
    assert _post(anon_client, "node-a", _beat(replicas=[bad])).status_code == 422


# --- retention ---


def _service(metrics_uow: InMemoryMetricsUoW, clock: FakeClock) -> MetricsService:
    return MetricsService(
        lambda: metrics_uow,
        apps=None,  # pyright: ignore[reportArgumentType]
        deploys=None,  # pyright: ignore[reportArgumentType]
        retention_hours=24,
        clock=clock,
    )


def test_purge_deletes_only_samples_older_than_the_retention(
    metrics_uow: InMemoryMetricsUoW, clock: FakeClock
):
    day = 24 * 3600
    _store(
        metrics_uow,
        _sample(clock, "old-r0", ago=day + 1),
        _sample(clock, "edge-r0", ago=day),  # exactly at the cutoff: kept
        _sample(clock, "new-r0", ago=day - 60),
        _sample(clock, "fresh-r0", ago=0),
    )

    deleted = asyncio.run(_service(metrics_uow, clock).purge())

    assert deleted == 1
    assert sorted(s.replica_id for s in metrics_uow.samples) == [
        "edge-r0",
        "fresh-r0",
        "new-r0",
    ]


def test_purge_works_through_old_samples_in_batches(
    metrics_uow: InMemoryMetricsUoW, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(metrics_module, "PURGE_BATCH", 2)
    _store(metrics_uow, *(_sample(clock, f"o{i}-r0", ago=30 * 3600 + i) for i in range(5)))
    _store(metrics_uow, _sample(clock, "fresh-r0", ago=1))

    assert asyncio.run(_service(metrics_uow, clock).purge()) == 5

    assert [s.replica_id for s in metrics_uow.samples] == ["fresh-r0"]
    assert metrics_uow.commits == 3  # 2 + 2 + 1


def test_deleting_an_app_drops_its_history(
    blog: None, client: TestClient, metrics_uow: InMemoryMetricsUoW, clock: FakeClock
):
    _store(metrics_uow, _sample(clock, "d1-r0", ago=1))

    assert client.delete("/apps/blog").status_code == 204

    assert metrics_uow.samples == []


# --- GET /apps/{name}/metrics ---


def test_series_are_one_per_replica_with_index_and_node(
    blog: None,
    client: TestClient,
    nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    metrics_uow: InMemoryMetricsUoW,
    clock: FakeClock,
):
    nodes.add(*NODE_B)
    _running(deploys_uow, [("node-a", 30001), ("node-b", 30002)])
    _store(
        metrics_uow,
        _sample(clock, "d1-r1", ago=10, cpu=70, node="node-b"),
        _sample(clock, "d1-r0", ago=10, cpu=20, node="node-a"),
    )

    body = client.get("/apps/blog/metrics").json()

    assert body["period"] == "15m"
    assert [(s["replica_id"], s["index"], s["node"]) for s in body["series"]] == [
        ("d1-r0", 0, "node-a"),
        ("d1-r1", 1, "node-b"),
    ]
    [[_, cpu, mem]] = body["series"][0]["points"]
    assert (cpu, mem) == (20, 100)


def test_samples_in_one_bucket_are_averaged(
    blog: None, client: TestClient, metrics_uow: InMemoryMetricsUoW, clock: FakeClock
):
    width = bucket_seconds("1h")
    # A bucket start well inside the last hour, on date_bin's grid.
    n = int((clock.now - BUCKET_ORIGIN).total_seconds() // width) - 100
    start = BUCKET_ORIGIN + timedelta(seconds=n * width)

    def at(offset: int, cpu: float, mem: int) -> ReplicaSample:
        return replace(
            _sample(clock, "d1-r0", ago=0, cpu=cpu, mem=mem),
            ts=start + timedelta(seconds=offset),
        )

    _store(metrics_uow, at(1, 10, 100), at(2, 30, 301), at(width + 1, 90, 900))

    [series] = client.get("/apps/blog/metrics?period=1h").json()["series"]

    assert [(p[1], p[2]) for p in series["points"]] == [(20, 200), (90, 900)]  # round(200.5)
    assert series["points"][0][0] == start.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_day_of_samples_is_downsampled_to_at_most_300_points(
    blog: None, client: TestClient, metrics_uow: InMemoryMetricsUoW, clock: FakeClock
):
    _store(metrics_uow, *(_sample(clock, "d1-r0", ago=5 * i) for i in range(24 * 720)))

    body = client.get("/apps/blog/metrics?period=24h").json()

    [series] = body["series"]
    assert body["bucket_seconds"] == 289
    assert MAX_POINTS - 3 <= len(series["points"]) <= MAX_POINTS
    stamps = [p[0] for p in series["points"]]
    assert stamps == sorted(stamps)


def test_samples_outside_the_period_are_left_out(
    blog: None, client: TestClient, metrics_uow: InMemoryMetricsUoW, clock: FakeClock
):
    _store(
        metrics_uow,
        _sample(clock, "d1-r0", ago=20 * 60),
        _sample(clock, "d1-r0", ago=60),
    )

    assert len(client.get("/apps/blog/metrics?period=15m").json()["series"][0]["points"]) == 1
    assert len(client.get("/apps/blog/metrics?period=1h").json()["series"][0]["points"]) == 2


def test_series_of_removed_replicas_are_not_live_but_keep_their_history(
    blog: None,
    client: TestClient,
    deploys_uow: InMemoryDeploysUoW,
    metrics_uow: InMemoryMetricsUoW,
    clock: FakeClock,
):
    _running(deploys_uow, [("node-a", 30001)])
    asyncio.run(add_running_deploy(deploys_uow, "d0", "blog", status="superseded"))
    _store(
        metrics_uow,
        _sample(clock, "d1-r0", ago=10),
        _sample(clock, "d0-r0", ago=60),
        _sample(clock, "ghost-r0", ago=60),  # no replica row at all
    )

    series = {s["replica_id"]: s for s in client.get("/apps/blog/metrics").json()["series"]}

    assert {rid: s["live"] for rid, s in series.items()} == {
        "d1-r0": True,
        "d0-r0": False,
        "ghost-r0": False,
    }
    assert len(series["d0-r0"]["points"]) == 1


def test_summary_sums_the_live_replicas_and_counts_ready_over_desired(
    blog: None,
    client: TestClient,
    nodes: FakeNodes,
    deploys_uow: InMemoryDeploysUoW,
    metrics_uow: InMemoryMetricsUoW,
    clock: FakeClock,
):
    nodes.add(*NODE_B)
    _running(deploys_uow, [("node-a", 30001), ("node-b", 30002)])
    _store(
        metrics_uow,
        _sample(clock, "d1-r0", ago=3, cpu=50, mem=100),
        _sample(clock, "d1-r0", ago=40, cpu=999, mem=999),  # older reading of the same replica
        _sample(clock, "d1-r1", ago=2, cpu=25, mem=300, node="node-b"),
        _sample(clock, "gone-r0", ago=60, cpu=500, mem=5000),  # silent for too long
    )

    summary = client.get("/apps/blog/metrics").json()["summary"]

    assert summary["cpu_cores"] == 0.75
    assert summary["mem_bytes"] == 400
    assert summary["mem_limit_bytes"] == 2000
    assert summary["ready_replicas"] == 2

    nodes.set_ready("node-b", False)
    assert client.get("/apps/blog/metrics").json()["summary"]["ready_replicas"] == 1


def test_an_app_without_data_has_an_empty_summary(blog: None, client: TestClient):
    body = client.get("/apps/blog/metrics").json()

    assert body["series"] == []
    assert body["summary"] == {
        "cpu_cores": 0,
        "mem_bytes": 0,
        "mem_limit_bytes": 0,
        "ready_replicas": 0,
        "desired_replicas": 1,
    }


@pytest.mark.parametrize("period", ["2h", "", "15", "1d"])
def test_an_unknown_period_is_rejected(blog: None, client: TestClient, period: str):
    resp = client.get(f"/apps/blog/metrics?period={period}")

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_only_the_owner_reads_metrics(
    blog: None, bob: TestClient, anon_client: TestClient
):
    assert bob.get("/apps/blog/metrics").status_code == 403
    assert bob.get("/apps/missing/metrics").status_code == 404
    assert anon_client.get("/apps/blog/metrics").status_code == 401


def test_replica_index_is_read_from_the_id():
    assert replica_index("0f3a-r2") == 2
    assert replica_index("weird") == 0
