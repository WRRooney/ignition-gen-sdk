"""Chart palette component models — all 7 ia.chart.* types.

Each class:
- Subclasses Component (which subclasses IgnitionBaseModel)
- Overrides model_config with extra="allow"
- Locks type via Literal["ia.chart.*"]
- Provides a typed Props sub-model (also extra="allow") for documented props

Props sub-models include documented 8.3 props as Optional fields. Unknown
props the gateway emits pass through extra="allow" without error.

Doc source: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
            perspective-components/perspective-chart-palette

Drift notes:
- Designer-exported Pie views use: data, colors, labels, title, titleColor, legendLabelColor,
  enableTransitions, showLabels, showLegend, threeDimensional, cutoutRadius,
  valueFormat, style — all documented props; extra="allow" absorbs any future
  gateway additions.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# Pie Chart
# ---------------------------------------------------------------------------

class PieProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    colors: list[str] | None = None
    labels: dict[str, Any] | None = None
    title: str | None = None
    titleColor: str | None = None
    legendLabelColor: str | None = None
    enableTransitions: bool | None = None
    showLabels: bool | None = None
    showLegend: bool | None = None
    threeDimensional: bool | None = None
    cutoutRadius: float | None = None
    valueFormat: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Pie(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.pie"] = "ia.chart.pie"
    props: PieProps = Field(default_factory=PieProps)


# ---------------------------------------------------------------------------
# Time Series Chart
# ---------------------------------------------------------------------------

class TimeSeriesProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    xAxis: dict[str, Any] | None = None
    yAxis: dict[str, Any] | None = None
    series: list[Any] | None = None
    legend: dict[str, Any] | None = None
    title: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class TimeSeries(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.timeseries"] = "ia.chart.timeseries"
    props: TimeSeriesProps = Field(default_factory=TimeSeriesProps)


# ---------------------------------------------------------------------------
# XY Chart
# ---------------------------------------------------------------------------

class XYProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    xAxis: dict[str, Any] | None = None
    yAxis: dict[str, Any] | None = None
    series: list[Any] | None = None
    legend: dict[str, Any] | None = None
    title: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class XY(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.xy"] = "ia.chart.xy"
    props: XYProps = Field(default_factory=XYProps)


# ---------------------------------------------------------------------------
# Power Chart
# ---------------------------------------------------------------------------

class PowerChartProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    config: dict[str, Any] | None = None
    # pens/plots are the load-bearing trend config. Declared as pass-through
    # lists (full pen schema still rides extra="allow") so they're at least visible
    # and emitted when set. Build pens with builders.view.power_chart_pen().
    pens: list[dict[str, Any]] | None = None
    plots: list[dict[str, Any]] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class PowerChart(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.powerchart"] = "ia.chart.powerchart"
    props: PowerChartProps = Field(default_factory=PowerChartProps)


# ---------------------------------------------------------------------------
# Gauge
# ---------------------------------------------------------------------------

class GaugeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    title: str | None = None
    unit: str | None = None
    arc: dict[str, Any] | None = None
    needle: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Gauge(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.gauge"] = "ia.chart.gauge"
    props: GaugeProps = Field(default_factory=GaugeProps)


# ---------------------------------------------------------------------------
# Simple Gauge
# ---------------------------------------------------------------------------

class SimpleGaugeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    title: str | None = None
    unit: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class SimpleGauge(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.simple-gauge"] = "ia.chart.simple-gauge"
    props: SimpleGaugeProps = Field(default_factory=SimpleGaugeProps)


# ---------------------------------------------------------------------------
# Chart Range Selector
# ---------------------------------------------------------------------------

class ChartRangeSelectorProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    startDate: str | None = None
    endDate: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class ChartRangeSelector(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.chart.chartrangeselector"] = "ia.chart.chartrangeselector"
    props: ChartRangeSelectorProps = Field(default_factory=ChartRangeSelectorProps)
