"""FormatTransform — Ignition 8.3 format transform.

Contract: the Component.format() helper always emits FormatTransform with
formatType='numeric' and formatValue=<printf-style string>. For datetime
formatting, construct FormatTransform(formatType='datetime',
formatValue=FormatDatetimeConfig(date=..., time=...)) directly.

Verified live shape (Designer-exported view.json):
    {"formatType": "numeric", "formatValue": "0.000", "type": "format"}
"""
from __future__ import annotations

from typing import Literal

from ..models.base import IgnitionBaseModel


class FormatDatetimeConfig(IgnitionBaseModel):
    """Datetime formatting style — used as FormatTransform.formatValue when formatType='datetime'."""
    date: Literal["short", "medium", "long", "full"] = "medium"
    time: Literal["short", "medium", "long", "full"] = "medium"


class FormatTransform(IgnitionBaseModel):
    # CRITICAL: discriminator value is "format" (Pydantic v2 Annotated discriminator dispatch).
    type: Literal["format"] = "format"
    formatType: Literal["numeric", "datetime"] = "numeric"
    formatValue: str | FormatDatetimeConfig   # REQUIRED — no default
