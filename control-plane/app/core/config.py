"""Settings from environment variables (prefix BULT_), parsed and validated at startup.

A missing or malformed variable makes `Settings()` raise one ValidationError that lists
every problem, so the API refuses to start instead of failing on the first request.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BULT_", populate_by_name=True)

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
    database_url: str = Field(validation_alias="DATABASE_URL")

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
