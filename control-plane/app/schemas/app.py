"""Pydantic schemas of the apps resource: what comes in and what goes out."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, computed_field, field_validator

# Names that must never become an app subdomain: they belong to the platform.
RESERVED_NAMES: frozenset[str] = frozenset({"api", "www", "admin", "registry"})

# DNS label regex:
# - ^[a-z0-9]: starts with an alphanumeric character
# - (?:[a-z0-9-]{0,61}[a-z0-9])?$: ends with alphanumeric, hyphens allowed internally, max 63 chars
DNS_LABEL_REGEX = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"


class AppCreate(BaseModel):
    """Request body of POST /apps."""

    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=63,
            pattern=DNS_LABEL_REGEX,
            description="DNS-compliant label used as the subdomain",
        ),
    ]
    preset: Literal["fastapi", "express"]
    repo_url: HttpUrl
    branch: str = "main"
    subdir: str = ""

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
    """Response body: what the API shows about an app."""

    name: str
    preset: Literal["fastapi", "express"]
    repo_url: str
    branch: str
    subdir: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        return f"https://{self.name}.bult.localhost"
