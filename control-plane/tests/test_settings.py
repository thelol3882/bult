"""Settings parsing from BULT_* variables."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_runners_accept_the_compose_format_and_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BULT_BUILDER", "b:1")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", "10.0.0.1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test/test")
    monkeypatch.setenv("BULT_JWT_SECRET", "s" * 32)

    monkeypatch.setenv("BULT_RUNNERS", "n1=10.0.0.5:50051, n2=10.0.0.6:50051")
    assert Settings().runners == {  # pyright: ignore[reportCallIssue]
        "n1": "10.0.0.5:50051",
        "n2": "10.0.0.6:50051",
    }

    monkeypatch.setenv("BULT_RUNNERS", '{"n1": "10.0.0.5:50051"}')
    assert Settings().runners == {"n1": "10.0.0.5:50051"}  # pyright: ignore[reportCallIssue]


def test_missing_variables_fail_with_all_of_them(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "BULT_BUILDER",
        "BULT_RUNNERS",
        "BULT_TRUSTED_PROXY",
        "DATABASE_URL",
        "BULT_JWT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValidationError) as info:
        Settings()  # pyright: ignore[reportCallIssue]

    assert {e["loc"][0] for e in info.value.errors()} == {
        "builder",
        "runners",
        "trusted_proxy",
        "DATABASE_URL",
        "jwt_secret",
    }


def test_short_jwt_secret_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BULT_JWT_SECRET", "short")
    with pytest.raises(ValidationError) as info:
        Settings()  # pyright: ignore[reportCallIssue]
    assert "jwt_secret" in {e["loc"][0] for e in info.value.errors()}
