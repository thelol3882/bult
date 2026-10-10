"""Choose nodes for app replicas.

Lesson 15: the first configured runner. Multi-node placement (spread
replicas of one app across nodes, skip dead nodes) is module 6.
"""


class NoRunnersError(Exception):
    """No runner nodes configured."""


def pick_runner(runner_names: list[str]) -> str:
    """The node for a new replica; NoRunnersError if the list is empty."""
    if not runner_names:
        raise NoRunnersError("no runner nodes configured")
    return runner_names[0]
