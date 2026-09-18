"""Tooltip — Ignition 8.3 component tooltip definition.

Verified live shape: every tooltip in Designer-exported view.json files
sets ONLY ``text``. The other fields are documented in 8.3 docs but are
extremely rare in real exports — kept Optional + None default so they
emit only when explicitly set (concrete defaults would emit unwanted noise).
"""
from __future__ import annotations

from typing import Any

from ..base import IgnitionBaseModel


class Tooltip(IgnitionBaseModel):
    text: str | None = None
    enabled: bool | None = None
    width: str | None = None
    delay: int | None = None
    sustain: int | None = None
    location: str | None = None
    tail: bool | None = None
    style: dict[str, Any] | None = None
