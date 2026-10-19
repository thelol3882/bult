"""Events the apps domain publishes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppDeleted:
    """The app is gone."""

    name: str


@dataclass(frozen=True)
class AppRoutesChanged:
    """The path routes of an app were replaced."""

    name: str
