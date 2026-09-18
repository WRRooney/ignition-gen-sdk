"""PropConfig — one propConfig entry: an optional Binding plus the entry-level
flags Perspective stores alongside it (``persistent``, ``access``,
``paramDirection``). The Component.@field_serializer reshapes a
list[PropConfig] into the gateway's dict-by-prop-path shape on emit.

Ground truth (Designer-authored views): component-level entries carry
``"persistent": true`` next to ``"binding"`` (~150 occurrences), and
binding-LESS entries exist — e.g. ``"meta.visible": {"access": "PROTECTED",
"persistent": true}`` — so ``binding`` is Optional and at least one field
must be present.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import ConfigDict, model_validator

from ..models.base import IgnitionBaseModel
from . import Binding  # the discriminated union from bindings/__init__.py


class OnChange(IgnitionBaseModel):
    """A property-change script attached to a propConfig entry.

    Ground truth (IndustryPack HOAControlType/ListView): the entry is EXACTLY
    ``{"enabled": <bool|null>, "script": "<tab-indented jython>"}``. It is NOT
    an event-handler envelope — a ``{"config": {...}, "type": "script"}`` shape
    is accepted by the gateway's JSON parser and then SILENTLY IGNORED (the
    script never runs, nothing is logged), so unknown keys fail loud here.

    The script runs with ``self``, ``currentValue``, ``previousValue``,
    ``origin`` and ``missedEvents`` in scope. Guard writes with
    ``if origin != 'Binding':`` — otherwise the binding's own updates
    re-trigger the script.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    script: str
    enabled: Optional[bool] = None


class PropConfig(IgnitionBaseModel):
    prop: str                       # e.g. "props.text", "props.value", "custom.response"
    binding: Optional[Binding] = None
    persistent: Optional[bool] = None
    access: Optional[Literal["PUBLIC", "PROTECTED", "PRIVATE"]] = None
    paramDirection: Optional[Literal["input", "output", "bidirectional"]] = None
    # Property-change script attached at the propConfig entry level. Modelled
    # (not a raw dict) because a wrong shape fails SILENTLY in the gateway.
    onChange: Optional[OnChange] = None

    @model_validator(mode="after")
    def _require_content(self) -> "PropConfig":
        if (
            self.binding is None
            and self.persistent is None
            and self.access is None
            and self.paramDirection is None
            and self.onChange is None
        ):
            raise ValueError(
                f"propConfig entry {self.prop!r} is empty — needs a 'binding' "
                "or at least one of persistent/access/paramDirection/onChange."
            )
        return self
