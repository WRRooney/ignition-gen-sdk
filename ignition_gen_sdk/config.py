"""Settings: gateway connection and workspace paths.

Resolution order (pydantic-settings): process environment, then a ``.env``
file in the current working directory. The token is never logged:
``__repr__``/``__str__`` replace it with ``[REDACTED]``.

Environment contract::

    IGNITION_URL        http://localhost:8088          (required)
    IGNITION_API_TOKEN  <name>:<secret>                 (required, full header value)
    IGNITION_DATA_DIR   /path/to/gateway/data           (required for disk writes)
    IGNITION_PROJECT    default Perspective project     (optional, default "Global")
    IGNITION_TAG_PROVIDER                               (optional, default "default")
    IGNITION_OPC_SERVER                                 (optional, default "Ignition OPC UA Server")
    IGNITION_STATE_DIR  SDK state dir                   (optional, default ./.ign)

State dir layout (gitignore it)::

    .ign/openapi.json        spec fetched from the gateway (``ign openapi fetch``)
    .ign/openapi.hash        spec hash sidecar
    .ign/client/             generated typed client (``ign openapi gen``)
    .ign/manifest/           push manifests (``ign diff``)
"""
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_STATE_DIR = Path(".ign")


class Settings(BaseSettings):
    """Gateway credentials and operational defaults.

    ``ignition_api_key`` holds the FULL ``X-Ignition-API-Token`` header value,
    i.e. ``<name>:<secret>`` exactly as the gateway shows it once when the API key is created.
    """

    ignition_api_key: str = Field(
        validation_alias=AliasChoices("IGNITION_API_TOKEN", "ignition_api_token"),
    )
    ignition_base_url: str = Field(
        default="http://localhost:8088",
        validation_alias=AliasChoices("IGNITION_URL", "ignition_url"),
    )
    ignition_default_project: str = Field(
        default="Global",
        validation_alias=AliasChoices("IGNITION_PROJECT", "ignition_project"),
    )
    ignition_default_tag_provider: str = Field(
        default="default",
        validation_alias=AliasChoices("IGNITION_TAG_PROVIDER", "ignition_tag_provider"),
    )
    ignition_default_opc_server: str = Field(
        default="Ignition OPC UA Server",
        validation_alias=AliasChoices("IGNITION_OPC_SERVER", "ignition_opc_server"),
    )
    # Gateway data directory (the one holding config/resources and projects).
    # Only needed for disk-backend writes; API-only use can leave it unset.
    ignition_data_root: Path = Field(
        default=Path("."),
        validation_alias=AliasChoices("IGNITION_DATA_DIR", "ignition_data_dir"),
    )
    ignition_state_dir: Path = Field(
        default=DEFAULT_STATE_DIR,
        validation_alias=AliasChoices("IGNITION_STATE_DIR", "ignition_state_dir"),
    )
    # Explicit overrides for the state-dir children. Unset = derived from state dir.
    openapi_spec_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("IGNITION_OPENAPI_SPEC_PATH", "openapi_spec_path"),
    )
    openapi_generated_client_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "IGNITION_OPENAPI_GENERATED_CLIENT_PATH", "openapi_generated_client_path"
        ),
    )
    openapi_hash_sidecar_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "IGNITION_OPENAPI_HASH_SIDECAR_PATH", "openapi_hash_sidecar_path"
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        populate_by_name=True,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ignition_api_key")
    @classmethod
    def _require_full_token(cls, v: str) -> str:
        name, sep, secret = v.partition(":")
        if not sep or not name or not secret:
            raise ValueError(
                "IGNITION_API_TOKEN must be the full header value '<name>:<secret>' "
                "as shown when the API key was created (Platform > Security > API Keys)."
            )
        return v

    def model_post_init(self, __context: object) -> None:  # noqa: D401
        state = self.ignition_state_dir
        if self.openapi_spec_path is None:
            self.openapi_spec_path = state / "openapi.json"
        if self.openapi_generated_client_path is None:
            self.openapi_generated_client_path = state / "client"
        if self.openapi_hash_sidecar_path is None:
            self.openapi_hash_sidecar_path = state / "openapi.hash"

    @property
    def manifest_dir(self) -> Path:
        return self.ignition_state_dir / "manifest"

    def __repr__(self) -> str:
        return (
            f"Settings(base_url={self.ignition_base_url!r}, "
            f"project={self.ignition_default_project!r}, "
            f"provider={self.ignition_default_tag_provider!r}, "
            f"data_dir={str(self.ignition_data_root)!r}, "
            f"api_key=[REDACTED])"
        )

    def __str__(self) -> str:
        return self.__repr__()
