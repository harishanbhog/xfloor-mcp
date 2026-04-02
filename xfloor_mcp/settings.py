"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for HTTP/stdio MCP server processes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="xfloor-mcp", alias="APP_NAME")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_log_level: str = Field(default="info", alias="APP_LOG_LEVEL")

    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default=["*"], alias="CORS_ALLOW_ORIGINS")
    cors_allow_credentials: bool = Field(default=True, alias="CORS_ALLOW_CREDENTIALS")
    cors_allow_methods: Annotated[list[str], NoDecode] = Field(default=["*"], alias="CORS_ALLOW_METHODS")
    cors_allow_headers: Annotated[list[str], NoDecode] = Field(default=["*"], alias="CORS_ALLOW_HEADERS")

    xfloor_base_url: str = Field(default="https://appfloor.in", alias="XFLOOR_BASE_URL")
    xfloor_timeout_seconds: float = Field(default=15.0, alias="XFLOOR_TIMEOUT_SECONDS")
    xfloor_default_auth_token: str | None = Field(
        default=None,
        alias="XFLOOR_DEFAULT_AUTH_TOKEN",
        validation_alias=AliasChoices("XFLOOR_DEFAULT_AUTH_TOKEN", "XFLOOR_DEFAULT_BEARER_TOKEN"),
    )
    xfloor_default_user_id: str | None = Field(default=None, alias="XFLOOR_DEFAULT_USER_ID")
    xfloor_default_app_id: str | None = Field(default=None, alias="XFLOOR_DEFAULT_APP_ID")
    xfloor_auth_mode: Literal["noauth", "oauth", "auto"] = Field(default="auto", alias="XFLOOR_AUTH_MODE")
    xfloor_oauth_stub_enabled: bool = Field(default=False, alias="XFLOOR_OAUTH_STUB_ENABLED")
    xfloor_oauth_stub_iss: str | None = Field(default=None, alias="XFLOOR_OAUTH_STUB_ISS")
    xfloor_oauth_stub_sub: str | None = Field(default=None, alias="XFLOOR_OAUTH_STUB_SUB")
    xfloor_oauth_stub_user_id: str = Field(default="oauth-dev-user", alias="XFLOOR_OAUTH_STUB_USER_ID")
    xfloor_auth0_domain: str | None = Field(default="dev-aobq6ntuhxzmcu6j.jp.auth0.com", alias="XFLOOR_AUTH0_DOMAIN")
    xfloor_auth0_issuer: str | None = Field(
        default="https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/",
        alias="XFLOOR_AUTH0_ISSUER",
    )
    xfloor_auth0_audience: str | None = Field(default="https://xFloorMCPTest", alias="XFLOOR_AUTH0_AUDIENCE")
    xfloor_oauth_resource: str | None = Field(default=None, alias="XFLOOR_OAUTH_RESOURCE")
    xfloor_host_adapter: str = Field(default="openai", alias="XFLOOR_HOST_ADAPTER")
    xfloor_widget_domain: str | None = Field(default="https://appfloor.in", alias="XFLOOR_WIDGET_DOMAIN")
    xfloor_widget_connect_domains: Annotated[list[str], NoDecode] = Field(
        default=["https://appfloor.in"], alias="XFLOOR_WIDGET_CONNECT_DOMAINS"
    )
    xfloor_widget_resource_domains: Annotated[list[str], NoDecode] = Field(
        default=["https://persistent.oaistatic.com", "https://appfloor.in"],
        alias="XFLOOR_WIDGET_RESOURCE_DOMAINS",
    )

    @field_validator(
        "cors_allow_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "xfloor_widget_connect_domains",
        "xfloor_widget_resource_domains",
        mode="before",
    )
    @classmethod
    def _parse_csv_list(cls, value: object) -> object:
        """Allow comma-separated env values in addition to JSON arrays."""

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("xfloor_oauth_stub_user_id")
    @classmethod
    def _validate_oauth_stub_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("XFLOOR_OAUTH_STUB_USER_ID cannot be empty.")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
