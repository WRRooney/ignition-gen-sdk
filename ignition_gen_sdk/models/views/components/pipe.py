"""Pipe model — Ignition 8.3 Perspective pipe network entity.

Single Pipe class. Variant-specific fields (lineVariant, start, end
for p&id; flanges for mimic) flow through extra="allow" — NOT declared as
typed attributes. Users supply them as keyword args and they appear in
model_dump output unchanged.

DO NOT subclass Component. Pipe is not a Perspective component — it is
an entity within a component's props. Inherits IgnitionBaseModel directly.

A PIDPipe / MimicPipe / AdvancedPipe subclass tree is intentionally NOT
modeled. The single-class approach with extra="allow" handles all
variants without per-variant typing overhead.

Doc: https://docs.inductiveautomation.com/docs/8.3/ignition-modules/perspective/
     working-with-perspective-components/perspective-pipes
"""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel


class PipeOrigin(IgnitionBaseModel):
    """Origin point for a pipe network node.

    Represents the position and connectivity of a single pipe node.
    Connections reference other PipeOrigin instances by position.
    """

    model_config = ConfigDict(extra="allow")

    x: float = 0.0
    y: float = 0.0
    connections: list[PipeOrigin] = Field(default_factory=list)


PipeOrigin.model_rebuild()


class Pipe(IgnitionBaseModel):
    """Single pipe-network entity model.

    appearance controls the pipe rendering variant:
    - "simple": basic 2D pipe line
    - "p&id": P&ID-style with lineVariant, start, end variant fields
    - "mimic": 3D mimic with flanges variant field
    - "auto": gateway-resolved appearance

    Variant-specific fields (lineVariant, start, end, flanges) are NOT
    declared as typed attributes. Pass them as keyword args — they ride
    through extra="allow" and appear in model_dump output:

        p = Pipe(appearance="p&id", lineVariant="solid", start="arrowInward")
        out = p.model_dump(exclude_none=True, mode="json")
        # out["lineVariant"] == "solid"  OK

    This is intentional. Do NOT add PIDPipe/MimicPipe/
    AdvancedPipe subclasses — variant fields via extra="allow" suffices.
    """

    model_config = ConfigDict(extra="allow")

    appearance: Literal["simple", "p&id", "mimic", "auto"] = "simple"
    name: str | None = None
    fill: str | None = None
    stroke: str | None = None
    width: float | None = None
    visible: bool | None = None
    origin: PipeOrigin | None = None


__all__ = [
    "PipeOrigin",
    "Pipe",
]
