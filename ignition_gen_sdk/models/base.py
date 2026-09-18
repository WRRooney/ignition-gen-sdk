"""IgnitionBaseModel — project-wide Pydantic v2 base.

Establishes:
- ConfigDict(use_enum_values=True, populate_by_name=True, extra="forbid")
- Credential JWE-field guard (rejects ciphertext, encrypted_key, iv, protected, tag)
- emit() helper: model_dump(exclude_none=True, mode="json")
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

# JWE/JOSE field names used by Ignition's encrypted credential storage.
# Constructing any model with these fields is a hard error — credentials
# must be set via the Gateway web UI, not hand-edited.
_CREDENTIAL_FIELDS = frozenset(
    {"ciphertext", "encrypted_key", "iv", "protected", "tag"}
)


class IgnitionBaseModel(BaseModel):
    """Base for every Ignition JSON model. Carries the project Pydantic config
    and the credential-field guard.
    """

    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def _block_credential_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            found = _CREDENTIAL_FIELDS & data.keys()
            if found:
                raise ValueError(
                    f"Encrypted credential fields are forbidden: {sorted(found)}. "
                    "Set credentials via the Ignition Gateway web UI."
                )
        return data

    def emit(self) -> dict:
        """Emit JSON-ready dict: drops None, serializes enums to their string value."""
        return self.model_dump(exclude_none=True, mode="json")
