"""QueryBinding — Ignition 8.3 query binding (named-query result, optional polling).

The binding's config field is `queryPath`, NOT `path`; every observed
live fixture and Designer export emits `queryPath`. This module locks that
name into the Pydantic model.

Polling-rate type: the
`polling.rate` field is a STRING on the wire ("5", "30", "1"), not an int.
This module models `rate: str = ""` and uses a `@field_validator(mode="before")`
to coerce any numeric input to its `str()` form so users can call
`.bind_query(polling_rate=5)` ergonomically and still get gateway-correct
emit ("rate": "5").

PollingConfig is defined here and re-used by:
- tag-history binding — same polling sub-object shape
- http binding — same polling sub-object shape

Verified live shape (Ignition 101/Feature Views/Perspective Features/
Bindings/view.json line 657-665 — the binding subtree; Component's
@field_serializer adds the outer "binding" wrapper on emit):

    {
      "config": {
        "polling": {"enabled": true, "rate": "5"},
        "queryPath": "Ignition 101/Named Query Binding"
      },
      "type": "query"
    }

Discriminator: `type: Literal["query"]` — used by the Binding discriminated
union in `bindings/__init__.py` for Pydantic v2 union dispatch.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator, model_serializer

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required so QueryBinding.model_rebuild() can resolve `list["Transform"]`
from ._emit import strip_binding_defaults


class PollingConfig(IgnitionBaseModel):
    """Polling sub-object for QueryBinding / TagHistoryBinding / HttpBinding.

    Gateway emits both fields as primitive non-None values even at their
    "off" state — `{"enabled": false, "rate": ""}`. The model uses
    `exclude_none` semantics globally (IgnitionBaseModel.emit()) which keeps
    these primitives in output; only explicit None Optional fields drop.

    rate is `str` on the wire — see module docstring.
    The @field_validator below makes int/float input ergonomic without
    breaking the string emit contract.
    """

    enabled: bool = False
    rate: str = ""

    @field_validator("rate", mode="before")
    @classmethod
    def _coerce_rate(cls, v):
        """Coerce numeric polling-rate input to its string form.

        Why: Gateway emits rate as string ("5", "30", "1"), but users naturally
        type integer milliseconds — `polling_rate=5000`. Pydantic v2 strict
        mode raises ValidationError on int -> str, lax mode silently coerces;
        both behaviors are wrong for our contract. This validator forces
        unambiguous str | int | float in, str out regardless of Pydantic mode.

        Rejects:
        - bool: bool is a subclass of int in Python; we explicitly check and
          reject because `polling_rate=True` is almost certainly a programmer
          error (meant `polling_enabled=True`).
        - everything else (list, dict, custom objects): loud error pointing at
          the canonical str|int|float contract.
        """
        if v is None:
            return ""
        # bool is a subclass of int — must check first to reject True/False
        # cleanly. `polling_rate=True` is a common typo for polling_enabled.
        if isinstance(v, bool):
            raise ValueError(
                f"polling rate must be str|int|float, got bool {v!r}. "
                "Did you mean polling_enabled?"
            )
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return v
        raise ValueError(
            f"polling rate must be str|int|float, got {type(v).__name__}"
        )


class QueryBindingConfig(IgnitionBaseModel):
    """Config sub-object for QueryBinding.

    REQUIRED:
    - queryPath: str — the named-query path. Field name is `queryPath`, NOT
      `path` (the gateway emits queryPath).

    OPTIONAL (all default to None; omitted from emit by exclude_none):
    - polling: PollingConfig — when present, the gateway re-runs the query
      at the configured rate (string-typed). Omit to disable polling entirely.
    - parameters: dict[str, str] — named-query parameter values. Keys are
      parameter names; values are expression-language strings the gateway
      evaluates per query execution. Not observed in Designer exports but
      documented in 8.3 docs; modeled as Optional dict.
    - returnFormat: Literal["auto", "json", "dataset", "scalar"] — desired
      result coercion. `auto` is the gateway default; explicit values are
      kept verbatim.
    - cacheAndShare: bool — gateway-side result caching/sharing flag.
    """

    queryPath: str  # REQUIRED — NOTE: queryPath, NOT path.
    polling: Optional[PollingConfig] = None
    parameters: Optional[dict[str, str]] = None
    returnFormat: Optional[Literal["auto", "json", "dataset", "scalar"]] = None
    cacheAndShare: Optional[bool] = None


class QueryBinding(IgnitionBaseModel):
    """Query binding — pulls data from a named query.

    Discriminator: type: Literal["query"]. Member of the Binding
    discriminated union (bindings/__init__.py).
    """

    type: Literal["query"] = "query"
    enabled: bool = True
    overlayOptOut: bool = False
    config: QueryBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys. See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref. Same idiom as property.py +
# tag.py + expression.py + expression_structure.py.
QueryBinding.model_rebuild()
