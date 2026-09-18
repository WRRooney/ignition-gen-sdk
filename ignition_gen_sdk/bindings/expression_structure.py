"""ExpressionStructureBinding — Ignition 8.3 expression-structure binding (multi-value composite).

Discriminator is "expr-struct" (with hyphen). `struct` is `dict[str, Any]` —
values can be expression-language strings (`"{../Slider.props.value}"`),
quoted literals (`"\"#CCCCFF\""`), primitives (`0`), or further nested
structures.

Verified live shape (Ignition 101/Feature Views/Perspective Features/
Bindings/view.json line 533-544 — the binding subtree; Component's
@field_serializer adds the outer "binding" wrapper on emit):

    {
      "config": {
        "struct": {
          "color": "\"#CCCCFF\"",
          "cornerRadius": 0,
          "width": "{../Slider.props.value}"
        },
        "waitOnAll": true
      },
      "type": "expr-struct"
    }

Design decisions:
- `struct: dict[str, Any] = Field(default_factory=dict)`. Default is an empty
  dict (the user wires actual key-expression pairs at construction time);
  inner-value schema is intentionally `Any` (this binding is schema-only, no
  expression parsing — values pass through verbatim to the gateway).
- `waitOnAll: bool = True`. Verified default in observed fixtures; users
  override to `False` for streaming-style updates.
- `transforms: list["Transform"]` — forward ref resolved at module bottom.

Discriminator distinction:

    ExpressionTransform        Literal["expression"]    (transform)
    ExpressionBinding          Literal["expr"]          (binding)
    ExpressionStructureBinding Literal["expr-struct"]   (binding, this file)

Three distinct values. The Binding discriminated union dispatches by
the `type` Literal; conflating any two breaks dispatch.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_serializer

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required so ExpressionStructureBinding.model_rebuild() can resolve `list["Transform"]`
from ._emit import strip_binding_defaults


class ExpressionStructureBindingConfig(IgnitionBaseModel):
    struct: dict[str, Any] = Field(default_factory=dict)
    waitOnAll: bool = True


class ExpressionStructureBinding(IgnitionBaseModel):
    # CRITICAL: "expr-struct" (with hyphen) — distinct from "expr" and "expression".
    type: Literal["expr-struct"] = "expr-struct"
    enabled: bool = True
    overlayOptOut: bool = False
    config: ExpressionStructureBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys. See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref. Same idiom as property.py + tag.py + expression.py.
ExpressionStructureBinding.model_rebuild()
