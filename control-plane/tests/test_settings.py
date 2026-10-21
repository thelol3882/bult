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


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("BULT_BUILDER", "b:1")
    monkeypatch.setenv("BULT_RUNNERS", "n1=10.0.0.5:50051")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", "10.0.0.1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test/test")
    monkeypatch.setenv("BULT_JWT_SECRET", "s" * 32)
    monkeypatch.delenv("BULT_NODE_TOKENS", raising=False)
    return monkeypatch


def test_node_tokens_default_to_none(base_env: pytest.MonkeyPatch):
    assert Settings().node_tokens == {}  # pyright: ignore[reportCallIssue]


def test_node_tokens_accept_the_compose_format_and_json(base_env: pytest.MonkeyPatch):
    a, b = "a" * 32, "b" * 40

    base_env.setenv("BULT_NODE_TOKENS", f"n1={a}, n2={b}")
    tokens = Settings().node_tokens  # pyright: ignore[reportCallIssue]
    assert {n: t.get_secret_value() for n, t in tokens.items()} == {"n1": a, "n2": b}

    base_env.setenv("BULT_NODE_TOKENS", f'{{"n1": "{a}"}}')
    assert list(Settings().node_tokens) == ["n1"]  # pyright: ignore[reportCallIssue]


def test_a_short_node_token_is_rejected_without_echoing_any_secret(
    base_env: pytest.MonkeyPatch,
):
    good = "g" * 40
    base_env.setenv("BULT_NODE_TOKENS", f"n1={good},n2=short-secret")

    with pytest.raises(ValidationError) as info:
        Settings()  # pyright: ignore[reportCallIssue]

    text = str(info.value)
    assert "n2" in text and "32" in text
    assert "short-secret" not in text and good not in text


def test_a_malformed_node_token_entry_is_rejected(base_env: pytest.MonkeyPatch):
    base_env.setenv("BULT_NODE_TOKENS", "just-a-word")

    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


def test_lb_algorithm_defaults_to_least_conn_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BULT_BUILDER", "b:1")
    monkeypatch.setenv("BULT_RUNNERS", "n1=10.0.0.5:50051")
    monkeypatch.setenv("BULT_TRUSTED_PROXY", "10.0.0.1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test/test")
    monkeypatch.setenv("BULT_JWT_SECRET", "s" * 32)

    assert Settings().lb_algorithm == "least_conn"  # pyright: ignore[reportCallIssue]
    monkeypatch.setenv("BULT_LB_ALGORITHM", "least_conn")
    assert Settings().lb_algorithm == "least_conn"  # pyright: ignore[reportCallIssue]

    monkeypatch.setenv("BULT_LB_ALGORITHM", "random")
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]
