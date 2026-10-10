"""Settings from environment variables (minimal; pydantic-settings in lesson 17)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    builder_addr: str  # BULT_BUILDER, e.g. "192.168.252.8:50051"
    runner_addrs: dict[
        str, str
    ]  # BULT_RUNNERS, e.g. "bult-node-1=192.168.252.6:50051,bult-node-2=…"
    trusted_proxy: str  # BULT_TRUSTED_PROXY


def _parse_runners(raw: str) -> dict[str, str]:
    """Parse comma-separated 'name=addr' pairs into a dictionary."""
    raw = raw.strip()
    if not raw:
        return {}

    runners: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(
                f"Invalid entry in BULT_RUNNERS: '{entry}'. Expected format 'name=addr'."
            )
        name, addr = entry.split("=", 1)
        runners[name.strip()] = addr.strip()

    return runners


def load_settings() -> Settings:
    """Read Settings from os.environ; a missing variable fails at startup, loudly."""
    required = {
        "BULT_BUILDER": "builder_addr",
        "BULT_RUNNERS": "runner_addrs",
        "BULT_TRUSTED_PROXY": "trusted_proxy",
    }

    missing = [var for var in required if var not in os.environ]
    if missing:
        raise KeyError(
            f"Startup failed: missing required environment variable(s): {', '.join(sorted(missing))}"
        )

    return Settings(
        builder_addr=os.environ["BULT_BUILDER"],
        runner_addrs=_parse_runners(os.environ["BULT_RUNNERS"]),
        trusted_proxy=os.environ["BULT_TRUSTED_PROXY"],
    )
