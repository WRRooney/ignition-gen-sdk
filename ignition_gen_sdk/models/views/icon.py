"""Icon — Ignition 8.3 icon reference (used in props for buttons, labels, etc.).

Verified live shape: ``{"path": "material/arrow_upward"}`` or
``{"path": "material/cloud_download", "color": "#229EF3"}``. Sometimes
nested in component props (e.g. ``button.props.image.icon``).
"""
from __future__ import annotations

from typing import Any

from ..base import IgnitionBaseModel


class Icon(IgnitionBaseModel):
    path: str | None = None
    color: str | None = None
    style: dict[str, Any] | None = None
