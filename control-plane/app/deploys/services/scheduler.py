"""Choose nodes for replicas: spread an app's replicas, then even out the load."""

from collections.abc import Collection, Mapping


class NoRunnersError(Exception):
    """No ready runner node to place a replica on."""


def pick_node(
    candidates: Collection[str],
    app_counts: Mapping[str, int],
    total_counts: Mapping[str, int],
) -> str:
    """The candidate with the fewest replicas of this app, then the fewest replicas in all,
    then the lowest name (so the choice is deterministic).

    `app_counts` counts the replicas of the deploy being placed: a redeploy replaces the
    old replicas, so those must not push the new ones away from their nodes.
    """
    if not candidates:
        raise NoRunnersError("no ready runner node")
    return min(
        candidates,
        key=lambda n: (app_counts.get(n, 0), total_counts.get(n, 0), n),
    )
