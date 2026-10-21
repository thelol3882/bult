"""Choose nodes for replicas: spread an app's replicas, then even out the load."""

from collections import Counter
from collections.abc import Collection, Mapping, Set
from datetime import UTC, datetime

from app.deploys.repositories.replicas import Replica


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


def pick_victims(replicas: list[Replica], count: int, ready: Set[str]) -> list[Replica]:
    """The replicas to retire when scaling down by `count`.

    Replicas that do not serve go first (dead, hung, crash-looping, on a node that is not
    ready): they give no capacity anyway. Then one at a time from the node holding the most
    replicas of this app, so the rest stays spread; on a tie the newest goes.
    """
    left = list(replicas)
    victims: list[Replica] = []
    for _ in range(min(count, len(left))):
        per_node = Counter(r.node for r in left)
        victim = max(
            left,
            key=lambda r: (
                not r.serving or r.node not in ready,
                per_node[r.node],
                r.placed_at or r.created_at or datetime.min.replace(tzinfo=UTC),
                r.index,
            ),
        )
        left.remove(victim)
        victims.append(victim)
    return victims
