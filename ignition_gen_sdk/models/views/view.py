"""View — Ignition 8.3 Perspective view top-level shell.

Verified live shape from Designer-exported view.json files:
- ``custom, params, props, root`` ALWAYS emit (often {} for the dicts)
- ``propConfig`` emits only when non-empty (52/169)
- ``events`` emits only when non-empty (1/169)

There is no top-level ``scripts`` field; the rare top-level key is
``events``. ``scripts`` is COMPONENT-level — see Component.scripts.

``params`` may legitimately hold dict values whose Python value
is ``None`` (e.g. ``{"TankNo": None}``). ``exclude_none=True`` only strips
Pydantic FIELDS — nested dict entries with None values survive (they
serialize to JSON ``null``). This is required behavior; do not change.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from ..base import IgnitionBaseModel
from .component import Component


class View(IgnitionBaseModel):
    custom: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    props: dict[str, Any] = Field(default_factory=dict)
    root: Component  # Required; no default — every view must have a root
    propConfig: dict[str, Any] | None = None  # exclude_none strips when None
    events: dict[str, Any] | None = None      # exclude_none strips when None
    # Designer "view permissions" gate, e.g.
    # {"type": "AnyOf", "securityLevels": [{"children": [...], "name": "Authenticated"}]}
    permissions: dict[str, Any] | None = None  # exclude_none strips when None

    @field_validator("params", mode="before")
    @classmethod
    def _reject_udt_parameter_shape(cls, v: Any) -> Any:
        """Reject UdtParameter-shaped values in params.

        Perspective view params must be plain scalars (str, int, float, bool, None).
        A UdtParameter shape is detected when a param value is a dict with BOTH
        'value' AND 'dataType' keys — the UDT tag parameter fingerprint.

        Correct:  params={"tagPath": "[default]Tanks/T01"}
        Wrong:    params={"tagPath": {"value": "", "dataType": "String"}}
        """
        if not isinstance(v, dict):
            return v
        for key, val in v.items():
            if isinstance(val, dict) and "value" in val and "dataType" in val:
                raise ValueError(
                    f"View param '{key}' looks like a UDT parameter "
                    f"({{'dataType': ..., 'value': ...}}) — Perspective view params "
                    f"must be plain scalars (str, int, float, bool, None). "
                    f"Correct: params={{'{key}': ''}}. "
                    f"Wrong: params={{'{key}': {{'value': '', 'dataType': 'String'}}}}."
                )
        return v

    @field_validator("props")
    @classmethod
    def _check_drop_config(cls, v: dict[str, Any]) -> dict[str, Any]:
        """``props.dropConfig.udts[]`` = Designer drop targets; each entry needs
        ``type`` (UDT type id), ``param`` (view param receiving the path) and
        ``action`` (``"path"``). A malformed entry is silently inert in the Designer."""
        for i, u in enumerate((v.get("dropConfig") or {}).get("udts") or []):
            missing = {"type", "param", "action"} - set(u if isinstance(u, dict) else ())
            if missing:
                raise ValueError(f"props.dropConfig.udts[{i}] missing {sorted(missing)}")
        return v


# Resolve forward ref for ``root: Component`` (Component is recursive).
View.model_rebuild()
