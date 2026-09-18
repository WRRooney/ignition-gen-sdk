"""Symbols palette component models — all 5 ia.symbol.* types.

Doc: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
     perspective-components/perspective-symbols-palette

CRITICAL: prefix is ia.symbol.* (singular). Do NOT add a trailing 's' to the prefix.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

class MotorProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    state: str | None = None  # "running", "stopped", "faulted", etc.
    animated: bool | None = None
    animationSpeed: int | None = None
    appearance: str | None = None  # "simple", "p&id", "mimic", "auto"
    label: dict[str, Any] | None = None
    value: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Motor(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.symbol.motor"] = "ia.symbol.motor"
    props: MotorProps = Field(default_factory=MotorProps)


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------

class PumpProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    state: str | None = None  # "running", "stopped", "faulted", etc.
    animated: bool | None = None
    animationSpeed: int | None = None
    appearance: str | None = None  # "simple", "p&id", "mimic", "auto"
    label: dict[str, Any] | None = None
    value: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Pump(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.symbol.pump"] = "ia.symbol.pump"
    props: PumpProps = Field(default_factory=PumpProps)


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------

class SensorProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    state: str | None = None
    animated: bool | None = None
    animationSpeed: int | None = None
    appearance: str | None = None
    label: dict[str, Any] | None = None
    value: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Sensor(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.symbol.sensor"] = "ia.symbol.sensor"
    props: SensorProps = Field(default_factory=SensorProps)


# ---------------------------------------------------------------------------
# Valve
# ---------------------------------------------------------------------------

class ValveProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    state: str | None = None
    animated: bool | None = None
    animationSpeed: int | None = None
    appearance: str | None = None
    open: bool | None = None
    label: dict[str, Any] | None = None
    value: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Valve(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.symbol.valve"] = "ia.symbol.valve"
    props: ValveProps = Field(default_factory=ValveProps)


# ---------------------------------------------------------------------------
# Vessel
# ---------------------------------------------------------------------------

class VesselProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    level: float | None = None
    state: str | None = None
    animated: bool | None = None
    animationSpeed: int | None = None
    appearance: str | None = None
    label: dict[str, Any] | None = None
    value: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Vessel(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.symbol.vessel"] = "ia.symbol.vessel"
    props: VesselProps = Field(default_factory=VesselProps)


__all__ = [
    "Motor",
    "MotorProps",
    "Pump",
    "PumpProps",
    "Sensor",
    "SensorProps",
    "Valve",
    "ValveProps",
    "Vessel",
    "VesselProps",
]
