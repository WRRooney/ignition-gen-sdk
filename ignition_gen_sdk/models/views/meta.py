"""Meta — Ignition 8.3 component meta block.

Verified live shape from Designer-exported view.json files:
only 4 keys ever observed — {name, hasDelegate, visible, tooltip}. All but
``name`` are emitted ONLY when explicitly set (Optional + exclude_none).

``name`` uses ``Field(default_factory=lambda: ...)`` so each ``Meta()``
constructs a fresh uuid-derived name; a class-load-time f-string would make
every instance share one default. Verified by
test_meta_name_default_factory_unique (100 Meta() instances, all distinct).

``Tooltip`` lives in ``tooltip.py``; Meta imports the dedicated class.
"""
from __future__ import annotations

from uuid import uuid4

from pydantic import Field, model_serializer

from ..base import IgnitionBaseModel
from .tooltip import Tooltip


class Meta(IgnitionBaseModel):
    name: str = Field(default_factory=lambda: f"component_{uuid4().hex[:8]}")
    hasDelegate: bool | None = None
    visible: bool | None = None
    tooltip: Tooltip | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler, _info):
        # Preserve EXPLICIT nulls. Designer writes e.g. "visible": null
        # on a root meta; exclude_none
        # would drop it and break round-trip fidelity. Re-add fields that were
        # explicitly set to None.
        out = handler(self)
        for f in ("hasDelegate", "visible", "tooltip"):
            if f in self.model_fields_set and getattr(self, f) is None and f not in out:
                out[f] = None
        return out
