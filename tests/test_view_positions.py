"""Tests for *ChildPosition models (per-container narrowing)."""
from __future__ import annotations

import pydantic
import pytest

from ignition_gen_sdk.models.views.positions import (
    BreakpointChildPosition,
    ColumnChildPosition,
    CoordinatePosition,
    FlexChildPosition,
    SplitChildPosition,
    TabChildPosition,
)


def _emit(model):
    return model.model_dump(exclude_none=True, mode="json")


# ---- FlexChildPosition ----

def test_flex_position_basic():
    assert _emit(FlexChildPosition(basis="56px", shrink=0)) == {"basis": "56px", "shrink": 0}


def test_flex_position_all_none_emits_empty():
    assert _emit(FlexChildPosition()) == {}


def test_flex_position_rejects_coord_field():
    """extra="forbid" prevents accidental cross-container fields."""
    with pytest.raises(pydantic.ValidationError):
        FlexChildPosition(x=10)  # type: ignore[call-arg]


# ---- CoordinatePosition ----

def test_coordinate_position_basic():
    assert _emit(CoordinatePosition(x=10, y=66, width=180, height=80)) == {
        "x": 10, "y": 66, "width": 180, "height": 80,
    }


def test_coordinate_position_rotate_dict():
    out = _emit(CoordinatePosition(rotate={"anchor": "44% 50%"}))
    assert out["rotate"] == {"anchor": "44% 50%"}


def test_coordinate_rejects_flex_field():
    with pytest.raises(pydantic.ValidationError):
        CoordinatePosition(basis="50%")  # type: ignore[call-arg]


# ---- SplitChildPosition ----

def test_split_position_left():
    assert _emit(SplitChildPosition(position="left")) == {"position": "left"}


def test_split_position_right():
    assert _emit(SplitChildPosition(position="right")) == {"position": "right"}


def test_split_position_invalid():
    with pytest.raises(pydantic.ValidationError):
        SplitChildPosition(position="diagonal")  # type: ignore[arg-type]


# ---- TabChildPosition ----

def test_tab_position():
    assert _emit(TabChildPosition(tabIndex=2)) == {"tabIndex": 2}


# ---- BreakpointChildPosition ----

def test_breakpoint_position_large():
    assert _emit(BreakpointChildPosition(size="large")) == {"size": "large"}


def test_breakpoint_position_invalid():
    with pytest.raises(pydantic.ValidationError):
        BreakpointChildPosition(size="medium")  # type: ignore[arg-type]


# ---- ColumnChildPosition ----

def test_column_position_with_breakpoints():
    bps = [
        {"colIndex": 0, "name": "sm", "order": 1, "rowIndex": 0, "span": 12},
        {"colIndex": 0, "name": "md", "order": 1, "rowIndex": 0, "span": 6},
    ]
    out = _emit(ColumnChildPosition(basis="50%", breakpoints=bps, grow=1, height=80))
    assert out["basis"] == "50%"
    assert out["breakpoints"] == bps
    assert out["grow"] == 1
    assert out["height"] == 80
