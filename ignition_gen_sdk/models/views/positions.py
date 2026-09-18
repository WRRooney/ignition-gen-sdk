"""Position models for container children — keyed by parent container type.

All 6 *ChildPosition classes — position-key sets verified across
Designer-exported view.json files.

Each *ChildPosition has its own narrow field set;
extra="forbid" (inherited from IgnitionBaseModel) rejects keys belonging
to a different container's position shape — so you cannot accidentally
construct FlexChildPosition(x=10) (a coord field).
"""
from __future__ import annotations

from typing import Any, Literal

from ..base import IgnitionBaseModel


class FlexChildPosition(IgnitionBaseModel):
    basis: str | None = None
    grow: int | float | None = None
    shrink: int | float | None = None
    display: bool | None = None
    dx: int | float | None = None
    dy: int | float | None = None
    height: int | float | None = None
    width: int | float | None = None
    relativeLocation: str | None = None


class CoordinatePosition(IgnitionBaseModel):
    x: int | float | None = None
    y: int | float | None = None
    width: int | float | None = None
    height: int | float | None = None
    # rotate is rare and shape-flexible: {anchor, angle?} — leave as dict
    rotate: dict[str, Any] | None = None
    relativeLocation: str | None = None


class SplitChildPosition(IgnitionBaseModel):
    # Verified: only "left"|"right"|"top"|"bottom" appear in Designer exports
    position: Literal["left", "right", "top", "bottom"] | None = None


class TabChildPosition(IgnitionBaseModel):
    # Verified: only tabIndex (int) appears
    tabIndex: int | None = None


class BreakpointChildPosition(IgnitionBaseModel):
    # Verified: only "large"|"small" appear in Designer exports
    size: Literal["large", "small"] | None = None


class ColumnBreakpoint(IgnitionBaseModel):
    """One responsive breakpoint of a Column container child.

    Verified shape from IA ground truth: across 230 Designer-exported
    views, EVERY column-child breakpoint entry has exactly these
    5 keys with NO variance (111/111). All required; ``extra="forbid"`` (from
    IgnitionBaseModel) catches a typo'd key author-time. ``name`` is the
    responsive size label ("sm"/"md"/"lg"/…). Pydantic coerces a plain dict
    into this model when it appears in ``ColumnChildPosition.breakpoints``, so
    existing dict-passing callers gain validation for free."""
    colIndex: int
    name: str
    order: int
    rowIndex: int
    span: int


class ColumnChildPosition(IgnitionBaseModel):
    basis: str | None = None
    # Each entry is a ColumnBreakpoint (5 keys, verified from 230 IA views).
    # Pydantic coerces dicts -> ColumnBreakpoint, so both forms validate.
    breakpoints: list[ColumnBreakpoint] | None = None
    grow: int | float | None = None
    height: int | float | None = None
