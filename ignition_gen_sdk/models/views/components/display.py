"""Display palette component models — all 24 ia.display.* types.

Each class:
- Subclasses Component (which subclasses IgnitionBaseModel)
- Overrides model_config with extra="allow"
- Locks type via Literal["ia.display.*"]
- Provides a typed Props sub-model (also extra="allow") for documented props

Props sub-models include all documented 8.3 props as Optional fields. Unknown
props the gateway emits pass through extra="allow" without error.

Doc source: https://docs.inductiveautomation.com/docs/8.3/appendix/components/
            perspective-components/perspective-display-palette
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from ...base import IgnitionBaseModel
from ..component import Component


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

class LabelProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    text: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    alignVertical: str | None = None  # drift: present in fixture, common in labels


class Label(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.label"] = "ia.display.label"
    props: LabelProps = Field(default_factory=LabelProps)


# ---------------------------------------------------------------------------
# Icon
# ---------------------------------------------------------------------------

class IconProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    path: str | None = None
    color: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Icon(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.icon"] = "ia.display.icon"
    props: IconProps = Field(default_factory=IconProps)


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

class ImageProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    stretch: str | None = None


class Image(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.image"] = "ia.display.image"
    props: ImageProps = Field(default_factory=ImageProps)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

class MarkdownProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Markdown(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.markdown"] = "ia.display.markdown"
    props: MarkdownProps = Field(default_factory=MarkdownProps)


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

class ProgressProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    direction: str | None = None
    showLabel: bool | None = None


class Progress(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.progress"] = "ia.display.progress"
    props: ProgressProps = Field(default_factory=ProgressProps)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

class TableProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    columns: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    selection: dict[str, Any] | None = None
    paging: dict[str, Any] | None = None


class Table(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.table"] = "ia.display.table"
    props: TableProps = Field(default_factory=TableProps)


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------

class TreeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    selection: dict[str, Any] | None = None


class Tree(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.tree"] = "ia.display.tree"
    props: TreeProps = Field(default_factory=TreeProps)


# ---------------------------------------------------------------------------
# Tag Browse Tree
# ---------------------------------------------------------------------------

class TagBrowseTreeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class TagBrowseTree(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.tag-browse-tree"] = "ia.display.tag-browse-tree"
    props: TagBrowseTreeProps = Field(default_factory=TagBrowseTreeProps)


# ---------------------------------------------------------------------------
# Alarm Journal Table
# ---------------------------------------------------------------------------

class AlarmJournalTableProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class AlarmJournalTable(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.alarmjournaltable"] = "ia.display.alarmjournaltable"
    props: AlarmJournalTableProps = Field(default_factory=AlarmJournalTableProps)


# ---------------------------------------------------------------------------
# Alarm Status Table
# ---------------------------------------------------------------------------

class AlarmStatusTableProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    alarmListConfig: dict[str, Any] | None = None


class AlarmStatusTable(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.alarmstatustable"] = "ia.display.alarmstatustable"
    props: AlarmStatusTableProps = Field(default_factory=AlarmStatusTableProps)


# ---------------------------------------------------------------------------
# Barcode
# ---------------------------------------------------------------------------

class BarcodeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: str | None = None
    barcodeType: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Barcode(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.barcode"] = "ia.display.barcode"
    props: BarcodeProps = Field(default_factory=BarcodeProps)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

class AudioProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    autoPlay: bool | None = None
    controls: bool | None = None


class Audio(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.audio"] = "ia.display.audio"
    props: AudioProps = Field(default_factory=AudioProps)


# ---------------------------------------------------------------------------
# Video Player
# ---------------------------------------------------------------------------

class VideoPlayerProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    autoPlay: bool | None = None
    controls: bool | None = None


class VideoPlayer(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.video-player"] = "ia.display.video-player"
    props: VideoPlayerProps = Field(default_factory=VideoPlayerProps)


# ---------------------------------------------------------------------------
# PDF Viewer
# ---------------------------------------------------------------------------

class PdfViewerProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class PdfViewer(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.pdf-viewer"] = "ia.display.pdf-viewer"
    props: PdfViewerProps = Field(default_factory=PdfViewerProps)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

class MapProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None
    center: dict[str, Any] | None = None
    zoom: float | None = None
    markers: list[Any] | None = None


class Map(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.map"] = "ia.display.map"
    props: MapProps = Field(default_factory=MapProps)


# ---------------------------------------------------------------------------
# Iframe (Inline Frame)
# ---------------------------------------------------------------------------

class IframeProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    source: str | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Iframe(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.iframe"] = "ia.display.iframe"
    props: IframeProps = Field(default_factory=IframeProps)


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------

class SparklineProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[Any] | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Sparkline(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.sparkline"] = "ia.display.sparkline"
    props: SparklineProps = Field(default_factory=SparklineProps)


# ---------------------------------------------------------------------------
# Linear Scale
# ---------------------------------------------------------------------------

class LinearScaleProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class LinearScale(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.linear-scale"] = "ia.display.linear-scale"
    props: LinearScaleProps = Field(default_factory=LinearScaleProps)


# ---------------------------------------------------------------------------
# LED Display
# ---------------------------------------------------------------------------

class LedDisplayProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: Any | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class LedDisplay(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.led-display"] = "ia.display.led-display"
    props: LedDisplayProps = Field(default_factory=LedDisplayProps)


# ---------------------------------------------------------------------------
# Moving Analog Indicator
# ---------------------------------------------------------------------------

class MovingAnalogIndicatorProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class MovingAnalogIndicator(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.moving-analog-indicator"] = "ia.display.moving-analog-indicator"
    props: MovingAnalogIndicatorProps = Field(default_factory=MovingAnalogIndicatorProps)


# ---------------------------------------------------------------------------
# Cylindrical Tank
# ---------------------------------------------------------------------------

class CylindricalTankProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class CylindricalTank(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.cylindrical-tank"] = "ia.display.cylindrical-tank"
    props: CylindricalTankProps = Field(default_factory=CylindricalTankProps)


# ---------------------------------------------------------------------------
# Thermometer
# ---------------------------------------------------------------------------

class ThermometerProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    value: float | None = None
    min: float | None = None
    max: float | None = None
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Thermometer(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.thermometer"] = "ia.display.thermometer"
    props: ThermometerProps = Field(default_factory=ThermometerProps)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class Dashboard(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.dashboard"] = "ia.display.dashboard"
    props: DashboardProps = Field(default_factory=DashboardProps)


# ---------------------------------------------------------------------------
# Equipment Schedule
# ---------------------------------------------------------------------------

class EquipmentScheduleProps(IgnitionBaseModel):
    model_config = ConfigDict(extra="allow")
    style: dict[str, Any] | None = None
    enabled: bool | None = None
    visible: bool | None = None


class EquipmentSchedule(Component):
    model_config = ConfigDict(extra="allow")
    type: Literal["ia.display.equipmentschedule"] = "ia.display.equipmentschedule"
    props: EquipmentScheduleProps = Field(default_factory=EquipmentScheduleProps)
