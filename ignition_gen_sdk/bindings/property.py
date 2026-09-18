"""PropertyBinding — Ignition 8.3 property binding (one-way property reference).

Verified live shape from Designer-exported view.json.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_serializer

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required in module namespace so PropertyBinding.model_rebuild() can resolve the `list["Transform"]` forward ref
from ._emit import strip_binding_defaults


class PropertyBindingConfig(IgnitionBaseModel):
    path: str                              # REQUIRED — no default empty string
    bidirectional: Optional[bool] = None   # not observed in fixtures; omit by default


class PropertyBinding(IgnitionBaseModel):
    type: Literal["property"] = "property"
    enabled: bool = True
    overlayOptOut: bool = False
    config: PropertyBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys before emit.

        Live samples never emit enabled:true / overlayOptOut:false /
        transforms:[] — keeping them would dirty Designer round-trips.
        See bindings/_emit.py for the canonical rationale.
        """
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref using the Transform symbol
# imported at module top.
PropertyBinding.model_rebuild()
