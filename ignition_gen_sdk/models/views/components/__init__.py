"""Components package — ComponentUnion callable-discriminator + _KNOWN_TYPES.

The callable discriminator pattern is required (NOT string-key Discriminator("type"))
because GenericComponent has type: str — not a Literal. Pydantic v2 raises
PydanticUserError at schema-construction time if a string-key discriminator is used
with a non-Literal member.

Verified working pattern: callable Discriminator + Tag annotation per union member.

New typed component classes extend `_UNION_ARGS` by adding their entries here.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union, get_args, get_origin

from pydantic import Discriminator, Tag

from .display import (
    AlarmJournalTable,
    AlarmStatusTable,
    Audio,
    Barcode,
    CylindricalTank,
    Dashboard,
    EquipmentSchedule,
    Icon,
    Iframe,
    Image,
    Label,
    LedDisplay,
    LinearScale,
    Map,
    Markdown,
    MovingAnalogIndicator,
    PdfViewer,
    Progress,
    Sparkline,
    Table,
    TagBrowseTree,
    Thermometer,
    Tree,
    VideoPlayer,
)
from .input import (
    Button,
    Checkbox,
    Dropdown,
    Slider,
    TextField,
    TextArea,
    NumericEntryField,
    DateTimeInput,
    DateTimePicker,
    RadioGroup,
    ToggleSwitch,
    MultiStateButton,
    OneShotButton,
    PasswordField,
    FileUpload,
    SignaturePad,
    BarcodeScannerInput,
)
from .navigation import HorizontalMenu, Link, MenuTree
from .symbols import Motor, Pump, Sensor, Valve, Vessel
from .chart import (
    ChartRangeSelector,
    Gauge,
    Pie,
    PowerChart,
    SimpleGauge,
    TimeSeries,
    XY,
)
from .embedding import Accordion, Carousel, EmbeddedView, FlexRepeater, ViewCanvas
from ._generic import GenericComponent


def _get_type_literal(cls: type) -> str | None:
    """Extract the Literal string from a typed component class's `type` field."""
    field = cls.model_fields.get("type")
    if field is None:
        return None
    annotation = field.annotation
    if get_origin(annotation) is Literal:
        args = get_args(annotation)
        return args[0] if args else None
    return None


def _build_known_types(union_args: tuple) -> frozenset[str]:
    """Auto-build _KNOWN_TYPES from Annotated[cls, Tag(...)] entries.

    Extracts the class from each Annotated[ClassName, Tag("ia.*")] using
    get_args, then calls _get_type_literal to pull the Literal value.
    GenericComponent has no Literal so it is skipped — "generic" never
    appears in _KNOWN_TYPES (only real ia.* strings do).
    """
    known: set[str] = set()
    for annotated_type in union_args:
        inner_args = get_args(annotated_type)
        if inner_args:
            cls = inner_args[0]
            lit_val = _get_type_literal(cls)
            if lit_val:
                known.add(lit_val)
    return frozenset(known)


# One Annotated[ClassName, Tag("ia.*")] per typed class.
# GenericComponent carries Tag("generic") at the END — no Literal on the class.
# New typed classes append their entries before the GenericComponent entry.
_UNION_ARGS: tuple = (
    Annotated[Label, Tag("ia.display.label")],
    Annotated[Icon, Tag("ia.display.icon")],
    Annotated[Image, Tag("ia.display.image")],
    Annotated[Markdown, Tag("ia.display.markdown")],
    Annotated[Progress, Tag("ia.display.progress")],
    Annotated[Table, Tag("ia.display.table")],
    Annotated[Tree, Tag("ia.display.tree")],
    Annotated[TagBrowseTree, Tag("ia.display.tag-browse-tree")],
    Annotated[AlarmJournalTable, Tag("ia.display.alarmjournaltable")],
    Annotated[AlarmStatusTable, Tag("ia.display.alarmstatustable")],
    Annotated[Barcode, Tag("ia.display.barcode")],
    Annotated[Audio, Tag("ia.display.audio")],
    Annotated[VideoPlayer, Tag("ia.display.video-player")],
    Annotated[PdfViewer, Tag("ia.display.pdf-viewer")],
    Annotated[Map, Tag("ia.display.map")],
    Annotated[Iframe, Tag("ia.display.iframe")],
    Annotated[Sparkline, Tag("ia.display.sparkline")],
    Annotated[LinearScale, Tag("ia.display.linear-scale")],
    Annotated[LedDisplay, Tag("ia.display.led-display")],
    Annotated[MovingAnalogIndicator, Tag("ia.display.moving-analog-indicator")],
    Annotated[CylindricalTank, Tag("ia.display.cylindrical-tank")],
    Annotated[Thermometer, Tag("ia.display.thermometer")],
    Annotated[Dashboard, Tag("ia.display.dashboard")],
    Annotated[EquipmentSchedule, Tag("ia.display.equipmentschedule")],
    # Input palette
    Annotated[Button, Tag("ia.input.button")],
    Annotated[Checkbox, Tag("ia.input.checkbox")],
    Annotated[Dropdown, Tag("ia.input.dropdown")],
    Annotated[Slider, Tag("ia.input.slider")],
    Annotated[TextField, Tag("ia.input.text-field")],
    Annotated[TextArea, Tag("ia.input.text-area")],
    Annotated[NumericEntryField, Tag("ia.input.numeric-entry-field")],
    Annotated[DateTimeInput, Tag("ia.input.date-time-input")],
    Annotated[DateTimePicker, Tag("ia.input.date-time-picker")],
    Annotated[RadioGroup, Tag("ia.input.radio-group")],
    Annotated[ToggleSwitch, Tag("ia.input.toggle-switch")],
    Annotated[MultiStateButton, Tag("ia.input.multi-state-button")],
    Annotated[OneShotButton, Tag("ia.input.oneshotbutton")],
    Annotated[PasswordField, Tag("ia.input.password-field")],
    Annotated[FileUpload, Tag("ia.input.fileupload")],
    Annotated[SignaturePad, Tag("ia.input.signature-pad")],
    Annotated[BarcodeScannerInput, Tag("ia.input.barcodescannerinput")],
    # Navigation palette
    Annotated[Link, Tag("ia.navigation.link")],
    Annotated[MenuTree, Tag("ia.navigation.menutree")],
    Annotated[HorizontalMenu, Tag("ia.navigation.horizontalmenu")],
    # Symbols palette (prefix: ia.symbol.* — singular, no trailing 's')
    Annotated[Motor, Tag("ia.symbol.motor")],
    Annotated[Pump, Tag("ia.symbol.pump")],
    Annotated[Sensor, Tag("ia.symbol.sensor")],
    Annotated[Valve, Tag("ia.symbol.valve")],
    Annotated[Vessel, Tag("ia.symbol.vessel")],
    # Chart palette
    Annotated[Pie, Tag("ia.chart.pie")],
    Annotated[TimeSeries, Tag("ia.chart.timeseries")],
    Annotated[XY, Tag("ia.chart.xy")],
    Annotated[PowerChart, Tag("ia.chart.powerchart")],
    Annotated[Gauge, Tag("ia.chart.gauge")],
    Annotated[SimpleGauge, Tag("ia.chart.simple-gauge")],
    Annotated[ChartRangeSelector, Tag("ia.chart.chartrangeselector")],
    # Embedding palette (note: all use ia.display.* prefix — not ia.embedding.*)
    Annotated[EmbeddedView, Tag("ia.display.view")],
    Annotated[FlexRepeater, Tag("ia.display.flex-repeater")],
    Annotated[ViewCanvas, Tag("ia.display.viewcanvas")],
    Annotated[Accordion, Tag("ia.display.accordion")],
    Annotated[Carousel, Tag("ia.display.carousel")],
    # Fallback — must be last
    Annotated[GenericComponent, Tag("generic")],
)

# Auto-built from Literal values; excludes "generic".
# Source-of-truth for ign component list.
_KNOWN_TYPES: frozenset[str] = _build_known_types(_UNION_ARGS)


def _component_discriminator(data: object) -> str:
    """Map incoming data to the correct Tag string.

    Known ia.* type strings return themselves.
    Unknown types (future gateway components, reporting, etc.) return "generic".
    """
    t = ""
    if isinstance(data, dict):
        t = data.get("type", "")
    elif hasattr(data, "type"):
        t = getattr(data, "type", "")
    return t if t in _KNOWN_TYPES else "generic"


# The union itself — Pydantic v2 callable Discriminator pattern.
# Union members carry Tag("ia.*") or Tag("generic") annotations.
# Discriminator function maps type string -> Tag value.
ComponentUnion = Annotated[
    Union[tuple(a for a in _UNION_ARGS)],
    Discriminator(_component_discriminator),
]


__all__ = [
    "ComponentUnion",
    "_KNOWN_TYPES",
    "GenericComponent",
    # Display palette exports
    "Label",
    "Icon",
    "Image",
    "Markdown",
    "Progress",
    "Table",
    "Tree",
    "TagBrowseTree",
    "AlarmJournalTable",
    "AlarmStatusTable",
    "Barcode",
    "Audio",
    "VideoPlayer",
    "PdfViewer",
    "Map",
    "Iframe",
    "Sparkline",
    "LinearScale",
    "LedDisplay",
    "MovingAnalogIndicator",
    "CylindricalTank",
    "Thermometer",
    "Dashboard",
    "EquipmentSchedule",
    # Input palette exports
    "Button",
    "Checkbox",
    "Dropdown",
    "Slider",
    "TextField",
    "TextArea",
    "NumericEntryField",
    "DateTimeInput",
    "DateTimePicker",
    "RadioGroup",
    "ToggleSwitch",
    "MultiStateButton",
    "OneShotButton",
    "PasswordField",
    "FileUpload",
    "SignaturePad",
    "BarcodeScannerInput",
    # Navigation palette exports
    "Link",
    "MenuTree",
    "HorizontalMenu",
    # Symbols palette exports
    "Motor",
    "Pump",
    "Sensor",
    "Valve",
    "Vessel",
    # Chart palette exports
    "Pie",
    "TimeSeries",
    "XY",
    "PowerChart",
    "Gauge",
    "SimpleGauge",
    "ChartRangeSelector",
    # Embedding palette exports
    "EmbeddedView",
    "FlexRepeater",
    "ViewCanvas",
    "Accordion",
    "Carousel",
]
