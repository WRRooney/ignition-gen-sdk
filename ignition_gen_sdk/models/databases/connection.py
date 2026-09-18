"""Database connection models — `ConnectionConfig` + `DatabaseConnection`.

Model layer for the database-connection resource.

Provides:
- `ConnectionConfig` — 25-field wire-format payload (verified against on-disk
  SQLite + MySQL gateway fixtures). The password JWE-refusal validator
  inspects both flat top-level JWE-key shape and the realistic nested
  `{type, data:{...JWE...}}` envelope (the existing `IgnitionBaseModel`
  top-level guard only catches the flat case).
- `DatabaseConnection` — 4-field envelope wrapper matching the gateway POST/PUT
  body shape. Refuses any payload containing a top-level `backupConfig`
  key (failover/redundant-database modeling is not implemented).
- `JWE_KEYS_REQUIRED` — canonical frozenset of the five JWE key names; single
  importable source for tests + future CLI / backend code.

References:
- `config/resources/core/ignition/database-connection/<name>/config.json`
  (SQLite happy-path and JWE-password refusal sources)
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import field_validator, model_validator

from ..base import IgnitionBaseModel

# Canonical JWE key signature (AES-256-GCM JOSE/JWE Embedded password payload).
# Tooling never constructs these — refuse on construct.
JWE_KEYS_REQUIRED: frozenset[str] = frozenset(
    {"ciphertext", "encrypted_key", "iv", "protected", "tag"}
)


class ConnectionConfig(IgnitionBaseModel):
    """25-field inner config payload for an Ignition database connection.

    Field defaults verified against both SQLite and MySQL
    on-disk fixtures. All names are camelCase on the wire — no aliasing
    needed.

    The `password` field accepts:
    - `None` (absent / no auth)
    - `str` (plaintext — gateway encrypts server-side on POST)
    - any value EXCEPT a JWE-shaped dict (flat 5-key or nested `{type,data:{...JWE...}}`)
    """

    driver: str
    translator: str
    connectURL: str
    includeSchemaInTableName: bool = False
    username: str = ""
    password: Optional[Any] = None
    connectionProps: str = ""
    connectionResetParams: str = ""
    defaultTransactionLevel: Literal[
        "DEFAULT",
        "READ_UNCOMMITTED",
        "READ_COMMITTED",
        "READ_REPEATABLE_READ",
        "SERIALIZABLE",
    ] = "DEFAULT"
    poolInitSize: int = 0
    poolMaxActive: int = 8
    poolMaxIdle: int = 8
    poolMinIdle: int = 0
    poolMaxWait: int = 5000
    validationQuery: str = "SELECT 1"
    testOnBorrow: bool = True
    testOnReturn: bool = False
    testWhileIdle: bool = False
    evictionRate: int = -1
    evictionTests: int = 3
    evictionTime: int = 1800000
    failoverProfile: str = ""
    failoverMode: Literal["STANDARD", "STICKY"] = "STANDARD"
    slowQueryLogThreshold: int = 60000
    validationSleepTime: int = 10000

    @field_validator("password", mode="before")
    @classmethod
    def _refuse_jwe_password(cls, v: Any) -> Any:
        """Refuse any password whose shape matches the AES-256-GCM JWE
        Embedded payload — either the flat 5-key dict or the nested
        `{type, data:{...JWE...}}` envelope used by Ignition on-disk.

        Plain strings, None, and non-dict types pass through unchanged.
        """
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, dict):
            # Defensive: check both nested ('data' sub-dict) and flat shapes.
            nested = v.get("data") if isinstance(v.get("data"), dict) else None
            candidate_keys = set(nested.keys()) if nested else set(v.keys())
            if JWE_KEYS_REQUIRED.issubset(candidate_keys):
                raise ValueError(
                    "Error: JWE credential payload refused: tooling cannot construct "
                    "encrypted-credential JWE payloads (AES-256-GCM). "
                    "Hint: Set the password via the Gateway UI at "
                    "/web/config/databases.connections after create."
                )
        return v


class DatabaseConnection(IgnitionBaseModel):
    """Outer envelope wrapper matching the gateway POST/PUT body shape.

    Exactly four fields: `name`, `description`, `enabled`, `config`. The
    `backupConfig` peer of `config` documented in the gateway schema is
    intentionally NOT modeled — any payload containing that key is
    refused at construct time with a Hint pointing to the Gateway UI.
    """

    name: str
    description: Optional[str] = None
    enabled: bool = True
    config: ConnectionConfig

    @model_validator(mode="before")
    @classmethod
    def _refuse_backup_config(cls, data: object) -> object:
        """Refuse any envelope containing a `backupConfig` key, regardless
        of value (None / empty dict / populated). Failover/redundant-database
        modeling is not implemented; the key is not modeled at all.
        """
        if isinstance(data, dict) and "backupConfig" in data:
            raise ValueError(
                "Error: backupConfig (failover/redundant database) is not supported "
                "by the SDK. Hint: Use the Gateway UI at "
                "/web/config/databases.connections to configure "
                "STANDARD/FAILOVER mode connections."
            )
        return data
