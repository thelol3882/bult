"""Settings from environment variables (prefix BULT_), parsed and validated at startup.

A missing or malformed variable makes `Settings()` raise one ValidationError that lists
every problem, so the API refuses to start instead of failing on the first request.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


MIN_NODE_TOKEN_LENGTH = 32
MAX_REPLICAS = 5  # per app


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BULT_",
        populate_by_name=True,
        hide_input_in_errors=True,  # a validation error must not echo secrets
    )

    builder: str  # BULT_BUILDER, e.g. "192.168.252.8:50051"
    # BULT_RUNNERS: "bult-node-1=192.168.252.6:50051,bult-node-2=…" (or a JSON object).
    # NoDecode: hand the raw string to the validator instead of parsing it as JSON first.
    runners: Annotated[dict[str, str], NoDecode]
    trusted_proxy: (
        str  # BULT_TRUSTED_PROXY: ingress address replicas trust for X-Forwarded-For
    )
    ingress_dir: str = "/routes"  # BULT_INGRESS_DIR
    apps_scheme: Literal["http", "https"] = "http"  # ingress serves plain HTTP today
    apps_domain: str = "bult.localhost"  # apps live at <name>.<apps_domain>
    # BULT_LB_ALGORITHM: how the ingress picks a replica (round_robin = nginx default).
    lb_algorithm: Literal["round_robin", "least_conn", "ip_hash"] = "least_conn"
    database_url: str = Field(validation_alias="DATABASE_URL")
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_ttl_seconds: int = 86400
    deploy_worker: bool = True  # BULT_DEPLOY_WORKER=false: no background worker (API-only tests)
    # BULT_NODE_TOKENS: "bult-node-1=<token>,bult-builder=<token>" (or a JSON object); a node
    # may only report itself under the name its token is bound to.
    node_tokens: Annotated[dict[str, SecretStr], NoDecode] = Field(default_factory=dict)
    node_ttl_seconds: float = Field(default=15.0, gt=0)  # silent for longer -> unhealthy
    # Silent for longer -> dead: its replicas are rescheduled on other nodes.
    node_dead_seconds: float = Field(default=60.0, gt=0)
    node_monitor: bool = True  # BULT_NODE_MONITOR=false: no status monitor (API-only tests)
    node_monitor_interval: float = Field(default=3.0, gt=0)
    # BULT_METRICS_RETENTION_HOURS: how long replica CPU/memory samples are kept.
    metrics_retention_hours: float = Field(default=24.0, gt=0)
    metrics_retention_interval: float = Field(default=300.0, gt=0)  # seconds between purges
    metrics_retention: bool = True  # BULT_METRICS_RETENTION=false: no purge loop (API-only tests)
    reconciler: bool = True  # BULT_RECONCILER=false: no replica reconciler (API-only tests)
    reconcile_interval: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def _dead_after_unhealthy(self) -> "Settings":
        if self.node_dead_seconds <= self.node_ttl_seconds:
            raise ValueError("node_dead_seconds must be greater than node_ttl_seconds")
        return self

    @field_validator("node_tokens", mode="before")
    @classmethod
    def _parse_node_tokens(cls, value: Any) -> Any:
        """Accept 'name=token,name=token' or a JSON object; tokens are at least 32 characters.

        Messages name the node, never the token.
        """
        if not isinstance(value, str):
            return value

        raw = value.strip()
        pairs: dict[str, str] = {}
        if raw.startswith("{"):
            pairs = json.loads(raw)
        else:
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                name, sep, token = entry.partition("=")
                if not sep or not name.strip() or not token.strip():
                    raise ValueError("invalid node token entry, expected 'name=token'")
                pairs[name.strip()] = token.strip()

        for name, token in pairs.items():
            if not isinstance(token, str) or len(token) < MIN_NODE_TOKEN_LENGTH:
                raise ValueError(
                    f"token of node '{name}' is shorter than {MIN_NODE_TOKEN_LENGTH} characters"
                )
        return pairs

    @field_validator("runners", mode="before")
    @classmethod
    def _parse_runners(cls, value: Any) -> Any:
        """Accept 'name=addr,name=addr' (the compose format) or a JSON object."""
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if raw.startswith("{"):
            return json.loads(raw)

        runners: dict[str, str] = {}
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, sep, addr = entry.partition("=")
            if not sep or not name.strip() or not addr.strip():
                raise ValueError(
                    f"invalid runner entry '{entry}', expected 'name=host:port'"
                )
            runners[name.strip()] = addr.strip()
        return runners
