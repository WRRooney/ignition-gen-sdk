"""Container subclasses — one per ia.container.* type-string.

All 6 type-strings verified against Designer-exported views.

Each subclass adds nothing structural to Component but locks ``type`` via
Literal so JSON output is byte-correct and incorrect type strings fail
at construction.

The breakpoint container's wire type-string is
``ia.container.breakpt`` — NOT ``ia.container.breakpoint``. The Designer
UI label says "Breakpoint Container" but the JSON file format uses the
abbreviated form. Literal enforcement defends against this.
"""
from __future__ import annotations

from typing import Any, Literal

from ..base import IgnitionBaseModel
from .component import Component


class TabSpec(IgnitionBaseModel):
    """One entry in a Tab container's ``props.tabs`` list.

    Verified against a Designer-exported Tab container (object form:
    ``{"disabled": false, "text": "Tab 1"}``). The Designer-canonical form
    is an object array; a bare string array is ALSO valid (some
    exchange views use ``["Widgets And Faceplates", …]``). ``tab_root``
    accepts either, so per-tab ``disabled``/``icon`` are now expressible
    through the typed builder.

    ``disabled`` is emitted explicitly (the gateway sample always carries it,
    even when ``false``); ``icon`` is omitted when unset.
    """
    text: str
    disabled: bool = False
    icon: dict[str, Any] | None = None


class FlexContainer(Component):
    type: Literal["ia.container.flex"] = "ia.container.flex"


class SplitContainer(Component):
    type: Literal["ia.container.split"] = "ia.container.split"


class CoordinateContainer(Component):
    type: Literal["ia.container.coord"] = "ia.container.coord"


class TabContainer(Component):
    type: Literal["ia.container.tab"] = "ia.container.tab"


class BreakpointContainer(Component):
    # breakpt NOT breakpoint
    type: Literal["ia.container.breakpt"] = "ia.container.breakpt"


class ColumnContainer(Component):
    type: Literal["ia.container.column"] = "ia.container.column"
