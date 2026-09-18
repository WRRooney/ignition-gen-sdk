"""ExpressionBinding — Ignition 8.3 expression binding (single-value computed).

Discriminator is "expr" (abbreviated). The TRANSFORM variant uses
"expression" (full word) — see transforms/expression.py. Do not confuse:

    Binding (this file)    -> Literal["expr"]
    Transform (other file) -> Literal["expression"]

These live in DIFFERENT discriminated unions (`Binding` vs `Transform`)
and dispatch by their respective Literal values. Conflating them
silently causes gateway rejection.

Verified live shape (Framework/Widgets/Gauge/view.json line 90-98 —
the binding subtree; Component's @field_serializer adds the outer
"binding" wrapper on emit):

    {
      "config": {
        "expression": "toBoolean({view.params.animate})"
      },
      "type": "expr"
    }

Design decisions:
- `ExpressionBindingConfig.expression` is REQUIRED (no default ""). Same
  rationale as PropertyBinding.config.path and TagBindingConfig.tagPath:
  a placeholder expression is a programmer error, not a valid
  intermediate state.
- `transforms` is `list["Transform"]` (forward ref resolved via
  `model_rebuild()` at module bottom), identical to property.py / tag.py.

Discriminator: `type: Literal["expr"]` — used by the Binding discriminated
union in `bindings/__init__.py`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_serializer

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required so ExpressionBinding.model_rebuild() can resolve `list["Transform"]`
from ._emit import strip_binding_defaults


class ExpressionBindingConfig(IgnitionBaseModel):
    expression: str  # REQUIRED — no default empty string; rejects seed pattern `expression: str = ""`


class ExpressionBinding(IgnitionBaseModel):
    # CRITICAL: "expr" (abbreviated) — ExpressionTransform.type is "expression" (full word).
    type: Literal["expr"] = "expr"
    enabled: bool = True
    overlayOptOut: bool = False
    config: ExpressionBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys. See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref. Same idiom as property.py + tag.py.
ExpressionBinding.model_rebuild()
