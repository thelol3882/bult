"""Pydantic schemas of the apps resource."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)

from app.apps.repositories.apps import App

# Platform-owned names that must not become app subdomains.
RESERVED_NAMES: frozenset[str] = frozenset({"api", "www", "admin", "registry"})

# DNS label: alphanumeric at both ends, hyphens inside, up to 63 characters.
DNS_LABEL_REGEX = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
NAME_FORMAT_MESSAGE = (
    "Use lowercase letters, digits and hyphens (up to 63 characters); "
    "must start and end with a letter or digit."
)


ENV_KEY_REGEX = re.compile(r"^[A-Z_][A-Z0-9_]*$")
ENV_RESERVED_KEYS: frozenset[str] = frozenset({"PORT", "FORWARDED_ALLOW_IPS"})
ENV_RESERVED_PREFIX = "BULT_"
ENV_MAX_KEYS = 100
ENV_MAX_KEY_LENGTH = 128
ENV_MAX_VALUE_BYTES = 4096


class EnvUpdate(BaseModel):
    """Request body of PUT /apps/{name}/env: the complete set of variables.

    Messages name keys, never values: the values are secrets.
    """

    model_config = ConfigDict(extra="forbid")

    env: dict[str, str]

    @field_validator("env")
    @classmethod
    def validate_env(cls, env: dict[str, str]) -> dict[str, str]:
        if len(env) > ENV_MAX_KEYS:
            raise ValueError(f"At most {ENV_MAX_KEYS} variables are allowed.")
        for key, value in env.items():
            if len(key) > ENV_MAX_KEY_LENGTH or not ENV_KEY_REGEX.fullmatch(key):
                raise ValueError(
                    f"Invalid variable name '{key[:ENV_MAX_KEY_LENGTH]}': "
                    "use uppercase letters, digits and underscores, "
                    "not starting with a digit."
                )
            if key in ENV_RESERVED_KEYS or key.startswith(ENV_RESERVED_PREFIX):
                raise ValueError(f"Variable '{key}' is reserved by the platform.")
            if len(value.encode()) > ENV_MAX_VALUE_BYTES:
                raise ValueError(
                    f"The value of '{key}' is longer than {ENV_MAX_VALUE_BYTES} bytes."
                )
            if "\x00" in value:
                raise ValueError(f"The value of '{key}' contains a NUL character.")
        return env


class AppUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["fastapi", "express"] | None = None
    repo_url: HttpUrl | None = None
    branch: str | None = None
    subdir: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("cannot be null")
        return value

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Repository URL must use the HTTPS scheme.")
        return value


class AppCreate(BaseModel):
    """Request body of POST /apps."""

    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=63,
            # Checked in validate_name_format; here only for OpenAPI.
            json_schema_extra={"pattern": DNS_LABEL_REGEX},
            description="DNS-compliant label used as the subdomain",
        ),
    ]
    preset: Literal["fastapi", "express"]
    repo_url: HttpUrl
    branch: str = "main"
    subdir: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def validate_name_format(cls, value: object) -> object:
        # Field(pattern=...) would leak the raw regex into the error message.
        if isinstance(value, str) and not re.fullmatch(DNS_LABEL_REGEX, value):
            raise ValueError(NAME_FORMAT_MESSAGE)
        return value

    @field_validator("name")
    @classmethod
    def validate_name_not_reserved(cls, value: str) -> str:
        if value in RESERVED_NAMES:
            raise ValueError(
                f"'{value}' is a reserved platform name and cannot be used."
            )
        return value

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Repository URL must use the HTTPS scheme.")
        return value


class AppOut(BaseModel):
    """An app as the API returns it."""

    name: str
    preset: Literal["fastapi", "express"]
    repo_url: str
    branch: str
    subdir: str
    created_at: datetime
    url: str  # built by AppService.url
    replicas: int
    env_keys: list[str]  # names only: the values are write-only

    @classmethod
    def from_app(cls, app: App, url: str) -> "AppOut":
        return cls(
            name=app.name,
            preset=app.preset,  # pyright: ignore[reportArgumentType]
            repo_url=app.repo_url,
            branch=app.branch,
            subdir=app.subdir,
            created_at=app.created_at,  # pyright: ignore[reportArgumentType]
            url=url,
            replicas=app.replicas,
            env_keys=sorted(app.env),
        )
