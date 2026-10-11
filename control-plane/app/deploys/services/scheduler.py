"""Choose nodes for replicas: the first configured runner (multi-node placement is planned)."""


class NoRunnersError(Exception):
    """No runner nodes configured."""


def pick_runner(runner_names: list[str]) -> str:
    """The node for a new replica."""
    if not runner_names:
        raise NoRunnersError("no runner nodes configured")
    return runner_names[0]
