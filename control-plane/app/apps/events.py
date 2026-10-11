"""Events the apps domain publishes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppDeleted:
    """The app is gone."""

    name: str
