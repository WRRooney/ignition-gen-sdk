"""NamedQuery — Ignition named-query project resource model.

A named query is TWO files under
``projects/<P>/ignition/named-query/<path>/``:

    query.sql      the SQL text, ``:param`` placeholders
    resource.json  scope/version envelope PLUS the whole query config in
                   ``attributes`` (database, parameters, caching, ...)

Unlike views there is no separate ``config.json`` — ``attributes`` IS the
config. Shape verified against the on-disk ExchangeResources DMC queries
(``ignition/named-query/DMC/Analysis/*/resource.json``).

``sqlType`` on a parameter is the Ignition DataType ORDINAL, not
``java.sql.Types`` — ``Int4`` is 2, ``String`` 7, ``DateTime`` 8, which is
exactly ``TagDataType``'s third tuple element, so that enum is the single
source of truth here too.

Query caching is the reason this model exists: ``cacheEnabled`` +
``cacheAmount`` make the GATEWAY hold one result set for all sessions, which
is what stops an N-session dashboard from running N copies of the same
aggregate. It only pays off when every session sends IDENTICAL parameters —
quantize any ``now()``-derived window to the poll bucket before binding.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .base import IgnitionBaseModel
from .tags.enums.tag_datatype import TagDataType

# Ignition writes the cache unit as one of these four tokens.
CacheUnit = Literal["SEC", "MIN", "HOUR", "DAY"]

# The Designer's three named-query flavours. "Query" returns a dataset;
# "Update" returns a row count; "Scalar Query" returns one value.
QueryType = Literal["Query", "Update", "Scalar Query"]


class NamedQueryParameter(IgnitionBaseModel):
    """One ``:identifier`` bind parameter."""

    identifier: str
    sqlType: str = Field(
        description="Ignition DataType string, e.g. 'String', 'Int4', 'DateTime'."
    )

    @field_validator("identifier")
    @classmethod
    def _identifier_is_bindable(cls, v: str) -> str:
        # The gateway's SQL parser finds parameters by scanning for ':' + name,
        # so a name with whitespace or punctuation silently never binds.
        if not v or not v.replace("_", "").isalnum():
            raise ValueError(
                f"parameter identifier {v!r} must be alphanumeric/underscore — "
                "the gateway binds parameters by scanning the SQL for ':<name>'."
            )
        return v

    @field_validator("sqlType")
    @classmethod
    def _known_datatype(cls, v: str) -> str:
        try:
            TagDataType(v)
        except ValueError:
            valid = ", ".join(sorted(m.value for m in TagDataType))
            raise ValueError(
                f"unknown sqlType {v!r}; expected one of: {valid}"
            ) from None
        return v

    def emit(self) -> dict:
        """The ``attributes.parameters[]`` entry the gateway expects."""
        return {
            "type": "Parameter",
            "identifier": self.identifier,
            "sqlType": TagDataType(self.sqlType)._int_value,
        }


class NamedQuery(IgnitionBaseModel):
    """A named query's configuration (everything except the SQL text)."""

    database: str
    parameters: list[NamedQueryParameter] = Field(default_factory=list)
    type: QueryType = "Query"
    enabled: bool = True

    # Caching — the whole point of the model. Gateway-scoped, shared by every
    # session, keyed on the parameter values.
    cacheEnabled: bool = False
    cacheAmount: int = 1
    cacheUnit: CacheUnit = "SEC"

    # Row cap. Ignition only enforces it when useMaxReturnSize is on; the
    # Designer still writes maxReturnSize either way.
    maxReturnSize: int = 100
    useMaxReturnSize: bool = False

    autoBatchEnabled: bool = False
    fallbackEnabled: bool = False
    fallbackValue: str = ""
    permissions: list[dict] = Field(
        default_factory=lambda: [{"zone": "", "role": ""}]
    )

    @field_validator("cacheAmount", "maxReturnSize")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    def attributes(self) -> dict:
        """The ``resource.json`` ``attributes`` block."""
        return {
            "autoBatchEnabled": self.autoBatchEnabled,
            "cacheAmount": self.cacheAmount,
            "cacheEnabled": self.cacheEnabled,
            "cacheUnit": self.cacheUnit,
            "database": self.database,
            "enabled": self.enabled,
            "fallbackEnabled": self.fallbackEnabled,
            "fallbackValue": self.fallbackValue,
            "maxReturnSize": self.maxReturnSize,
            "parameters": [p.emit() for p in self.parameters],
            "permissions": self.permissions,
            "type": self.type,
            "useMaxReturnSize": self.useMaxReturnSize,
        }
