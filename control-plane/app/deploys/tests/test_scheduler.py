"""Placement: spread an app's replicas, then even out the node load."""

import pytest

from app.deploys.services.scheduler import NoRunnersError, pick_node


def test_the_node_with_fewest_replicas_of_the_app_wins():
    assert pick_node(["a", "b", "c"], {"a": 2, "b": 1}, {}) == "c"
    assert pick_node(["a", "b"], {"a": 2, "b": 1}, {"a": 0, "b": 9}) == "b"


def test_a_tie_goes_to_the_node_with_fewer_replicas_in_total():
    assert pick_node(["a", "b"], {"a": 1, "b": 1}, {"a": 5, "b": 2}) == "b"


def test_a_full_tie_goes_to_the_lowest_name():
    assert pick_node(["b", "a", "c"], {}, {}) == "a"


def test_three_replicas_on_two_nodes_make_two_and_one():
    app: dict[str, int] = {}
    for _ in range(3):
        node = pick_node(["node-a", "node-b"], app, {})
        app[node] = app.get(node, 0) + 1

    assert app == {"node-a": 2, "node-b": 1}


def test_no_candidates_is_an_error():
    with pytest.raises(NoRunnersError):
        pick_node([], {}, {})
