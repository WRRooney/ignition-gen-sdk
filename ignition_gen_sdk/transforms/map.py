"""MapTransform — Ignition 8.3 map transform (input value -> output value, with optional fallback).

Contract: the Component.map() helper accepts a single dict argument. If
the dict contains a 'fallback' key, it is popped and used as MapTransform.fallback;
all remaining keys are paired into MapMapping(input=k, output=v) entries.

Verified live shape (Designer-exported view.json):
    {
      "fallback": "framework/sidebar-items",
      "inputType": "scalar",
      "mappings": [
        {"input": "/components/containers/column",
         "output": "framework/sidebar-items-selected"}
      ],
      "outputType": "scalar",
      "type": "map"
    }
"""
from __future__ import annotations

from typing import Literal, Optional

from ..models.base import IgnitionBaseModel


class NumericRange(IgnitionBaseModel):
    """Numeric input range for MapMapping when MapTransform.inputType == 'range'."""
    min: Optional[int | float] = None
    max: Optional[int | float] = None
    exclusiveMin: bool = False
    exclusiveMax: bool = False


class MapMapping(IgnitionBaseModel):
    """A single input -> output entry in MapTransform.mappings.

    input may be a scalar literal (bool | str | int | float) or a NumericRange when
    the parent MapTransform.inputType == 'range'.

    ``bool`` is listed FIRST: Pydantic's lax int validation accepts ``True`` as
    ``1``, so a union without bool silently turned a Designer-authored
    ``{"input": true, "output": false}`` (position.display gates, IndustryPack
    ground truth) into ``{"input": 1, "output": 0}`` on round-trip.
    """
    input: Optional[bool | int | float | str | NumericRange] = None
    output: Optional[bool | int | float | str | dict] = None


class MapTransform(IgnitionBaseModel):
    # CRITICAL: discriminator value is "map" (Pydantic v2 Annotated discriminator dispatch).
    type: Literal["map"] = "map"
    inputType: Literal["scalar", "range", "expression"] = "scalar"
    outputType: Literal[
        "scalar", "expression", "color", "inline-style", "style-list", "document"
    ] = "scalar"
    mappings: list[MapMapping]                              # REQUIRED — no default
    fallback: Optional[bool | str | int | float | dict] = None  # optional; omitted on emit when None; bool first (see MapMapping)
