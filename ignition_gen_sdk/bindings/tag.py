"""TagBinding — Ignition 8.3 tag binding (direct / indirect / expression modes).

Indirect references shape: `references` is a `dict[str, str]` (string-keyed
map of placeholder name -> expression-language string), NOT a list of
`{name, value}` objects. EVERY live Designer export uses the dict form.

Verified live shapes (these are the *binding subtrees* — Component's
@field_serializer adds the outer "binding" wrapper):

Direct mode (Bindings/view.json line 99-103):
    {
      "config": {
        "fallbackDelay": 2.5,
        "mode": "direct",
        "tagPath": "[Sample_Tags]Random/RandomInteger1"
      },
      "type": "tag"
    }

Indirect mode (Framework/Widgets/Gauge/view.json line 131-144):
    {
      "config": {
        "fallbackDelay": 2.5,
        "mode": "indirect",
        "references": {"1": "{view.params.tagPath}"},
        "tagPath": "{1}"
      },
      "type": "tag"
    }

Design decisions:
- Single TagBindingConfig class with `references: Optional[dict[str, str]] = None`
  (no separate IndirectTagBindingConfig class). Indirect
  mode is differentiated by the `mode` field + presence of `references`, not
  by class identity.
- `mode` is `TagBindingMode` enum (NOT bare str). With IgnitionBaseModel's
  `use_enum_values=True`, validation coerces the enum to its string value at
  construction; emit-time gives the gateway-expected "direct"/"indirect"/
  "expression" strings without further work.
- `tagPath` is REQUIRED (no default empty string). The seed's `tagPath: str = ""`
  pattern is what makes empty tag bindings silently construct; we reject that.
- `bidirectional` + `publishInitial` are `Optional[bool] = None`. The seed's
  `publishInitial: bool = False` default would emit `publishInitial: false`
  into every direct binding — observed fixtures omit this field by default.
- `fallbackDelay: float = 2.5` — verified default in every fixture (both
  direct and indirect entries always include this).
- `@field_validator("references", mode="before")` enforces dict[str, str] at
  construction; rejects non-dict, non-string keys, non-string values with
  actionable diagnostic messages that include the example shape.

Discriminator: `type: Literal["tag"]` — used by the Binding discriminated
union in `bindings/__init__.py` for Pydantic v2 union dispatch.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator, model_serializer

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — Transform symbol required in module namespace so TagBinding.model_rebuild() can resolve `list["Transform"]`
from ._emit import strip_binding_defaults
from .enums import TagBindingMode


class TagBindingConfig(IgnitionBaseModel):
    # Field order matches the fixture observations + the seed's intent.
    mode: TagBindingMode = TagBindingMode.DIRECT
    tagPath: str                                       # REQUIRED — no default empty
    bidirectional: Optional[bool] = None
    fallbackDelay: float = 2.5
    publishInitial: Optional[bool] = None
    # dict[str, str], NOT a list of {name, value} objects.
    # Verified shape: {"1": "{view.params.tagPath}"}.
    references: Optional[dict[str, str]] = None

    @field_validator("references", mode="before")
    @classmethod
    def _validate_references(cls, v, info):
        """Enforce dict[str, str] shape at construction.

        Rejects:
        - non-dict (list, str, int, ...) — common when porting from the seed's
          list[IndirectReference] shape
        - dicts with non-string keys (e.g. int keys from a careless port)
        - dicts with non-string values (e.g. nested dicts, ints)

        All errors include the canonical example so the user can fix the
        shape without consulting docs.
        """
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError(
                f"`references` must be a dict[str, str], got {type(v).__name__}. "
                "Example: {'1': '{view.params.tagPath}'}. "
                "The seed's list[IndirectReference] shape is NOT what the gateway emits."
            )
        coerced: dict[str, str] = {}
        for k, val in v.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"`references` has non-string key {k!r} (type {type(k).__name__}). "
                    "All keys must be strings (typically '1', '2', 'tagPath', etc.). "
                    "Example: {'1': '{view.params.tagPath}'}."
                )
            if not isinstance(val, str):
                raise ValueError(
                    f"`references[{k!r}]` has non-string value {val!r} "
                    f"(type {type(val).__name__}). All values must be strings "
                    "(expression-language placeholders). "
                    "Example: {'1': '{view.params.tagPath}'}."
                )
            coerced[k] = val
        return coerced


class TagBinding(IgnitionBaseModel):
    type: Literal["tag"] = "tag"
    enabled: bool = True
    overlayOptOut: bool = False
    config: TagBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys (enabled,
        overlayOptOut, empty transforms). See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve the `list["Transform"]` forward ref using the Transform symbol
# imported at module top (discriminated union including ExpressionTransform).
TagBinding.model_rebuild()
