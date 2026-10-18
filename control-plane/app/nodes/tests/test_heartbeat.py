"""POST /internal/nodes/heartbeat: node tokens bound to the node's name."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.nodes.uow import InMemoryNodesUoW
from tests.fakes import NODE_TOKENS, FakeClock

URL = "/internal/nodes/heartbeat"
BEAT = {
    "name": "node-a",
    "address": "10.0.0.5:50051",
    "role": "runner",
    "version": "v1",
    "capacity": {"cpus": 2, "memory_bytes": 2147483648},
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _stored(nodes_uow: InMemoryNodesUoW):
    return asyncio.run(nodes_uow.nodes.list())


def test_a_valid_heartbeat_registers_the_node(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW, clock: FakeClock
):
    resp = anon_client.post(URL, json=BEAT, headers=_auth(NODE_TOKENS["node-a"]))

    assert resp.status_code == 204
    [node] = _stored(nodes_uow)
    assert (node.name, node.address, node.role, node.version) == (
        "node-a",
        "10.0.0.5:50051",
        "runner",
        "v1",
    )
    assert (node.cpus, node.memory_bytes) == (2, 2147483648)
    assert node.last_seen_at == clock.now


def test_a_second_heartbeat_refreshes_last_seen_and_the_address(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW, clock: FakeClock
):
    headers = _auth(NODE_TOKENS["node-a"])
    anon_client.post(URL, json=BEAT, headers=headers)
    first = _stored(nodes_uow)[0]

    clock.advance(5)
    moved = {**BEAT, "address": "10.0.0.9:50051"}
    assert anon_client.post(URL, json=moved, headers=headers).status_code == 204

    [node] = _stored(nodes_uow)
    assert node.address == "10.0.0.9:50051"
    assert node.last_seen_at == clock.now > first.last_seen_at
    assert node.created_at == first.created_at


def test_without_a_token_the_node_is_not_registered(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW
):
    resp = anon_client.post(URL, json=BEAT)

    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_node_token"
    assert _stored(nodes_uow) == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer nope"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic " + NODE_TOKENS["node-a"]},
        {"Authorization": NODE_TOKENS["node-a"]},
    ],
)
def test_a_wrong_or_malformed_token_is_rejected(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW, headers: dict[str, str]
):
    resp = anon_client.post(URL, json=BEAT, headers=headers)

    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_node_token"
    assert _stored(nodes_uow) == []


def test_the_token_of_another_node_cannot_speak_for_this_one(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW
):
    # node-b's valid token, node-a's name: would let node-b replace node-a's address.
    resp = anon_client.post(URL, json=BEAT, headers=_auth(NODE_TOKENS["node-b"]))

    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_node_token"
    assert _stored(nodes_uow) == []


def test_a_node_without_a_configured_token_is_rejected(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW
):
    stranger = {**BEAT, "name": "node-z"}

    for token in NODE_TOKENS.values():
        assert anon_client.post(URL, json=stranger, headers=_auth(token)).status_code == 401
    assert _stored(nodes_uow) == []


def test_every_answer_is_the_same_whatever_was_wrong(anon_client: TestClient):
    wrong = anon_client.post(URL, json=BEAT, headers=_auth("x" * 40))
    foreign = anon_client.post(URL, json=BEAT, headers=_auth(NODE_TOKENS["node-b"]))
    unknown = anon_client.post(
        URL, json={**BEAT, "name": "node-z"}, headers=_auth("x" * 40)
    )

    bodies = {r.json()["detail"] for r in (wrong, foreign, unknown)}
    assert bodies == {"Invalid node token"}


@pytest.mark.parametrize(
    "change",
    [
        {"role": "boss"},
        {"name": "Bad Name"},
        {"address": "no-port"},
        {"address": "host:99999999"},
        {"capacity": {"cpus": -1}},
        {"extra": 1},
    ],
)
def test_invalid_payloads_are_422(
    anon_client: TestClient, nodes_uow: InMemoryNodesUoW, change: dict
):
    resp = anon_client.post(
        URL, json={**BEAT, **change}, headers=_auth(NODE_TOKENS["node-a"])
    )

    assert resp.status_code == 422
    assert _stored(nodes_uow) == []


def test_a_user_login_is_not_a_node_token(anon_client: TestClient, client: TestClient):
    user_token = client.headers["Authorization"]

    resp = anon_client.post(URL, json=BEAT, headers={"Authorization": user_token})

    assert resp.status_code == 401


def test_tokens_never_reach_the_logs_or_responses(
    anon_client: TestClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level("DEBUG"):
        ok = anon_client.post(URL, json=BEAT, headers=_auth(NODE_TOKENS["node-a"]))
        bad = anon_client.post(URL, json=BEAT, headers=_auth(NODE_TOKENS["node-b"]))

    for token in NODE_TOKENS.values():
        assert token not in caplog.text
        assert token not in ok.text + bad.text
