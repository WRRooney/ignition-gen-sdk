"""Tests for container subclasses."""
from __future__ import annotations

import pydantic
import pytest

from ignition_gen_sdk.models.views.containers import (
    BreakpointContainer,
    ColumnContainer,
    CoordinateContainer,
    FlexContainer,
    SplitContainer,
    TabContainer,
)


def test_flex_container_type():
    assert FlexContainer().type == "ia.container.flex"


def test_split_container_type():
    assert SplitContainer().type == "ia.container.split"


def test_coordinate_container_type():
    assert CoordinateContainer().type == "ia.container.coord"


def test_tab_container_type():
    assert TabContainer().type == "ia.container.tab"


def test_breakpoint_container_type_uses_breakpt_not_breakpoint():
    """Wire format is 'ia.container.breakpt', NOT 'ia.container.breakpoint'."""
    assert BreakpointContainer().type == "ia.container.breakpt"


def test_column_container_type():
    assert ColumnContainer().type == "ia.container.column"


def test_container_rejects_wrong_type_string():
    """Literal enforces — a bogus type string at construction fails."""
    with pytest.raises(pydantic.ValidationError):
        FlexContainer(type="ia.container.flox")  # type: ignore[arg-type]


def test_breakpoint_container_rejects_breakpoint_typo():
    """The classic 'breakpoint' (full word) typo — must fail."""
    with pytest.raises(pydantic.ValidationError):
        BreakpointContainer(type="ia.container.breakpoint")  # type: ignore[arg-type]


def test_all_6_containers_emit_with_their_type():
    """Every container's emit() includes its locked type string."""
    expected = {
        FlexContainer: "ia.container.flex",
        SplitContainer: "ia.container.split",
        CoordinateContainer: "ia.container.coord",
        TabContainer: "ia.container.tab",
        BreakpointContainer: "ia.container.breakpt",
        ColumnContainer: "ia.container.column",
    }
    for cls, expected_type in expected.items():
        out = cls().emit()
        assert out["type"] == expected_type, f"{cls.__name__} emits {out['type']!r}"


def test_containers_inherit_component_fields():
    """Container subclasses get props/children/etc from Component parent.

    Empty children is OMITTED from emit (matches
    every observed gateway sample — no fixture emits an empty children
    list at the component level).
    """
    c = SplitContainer(props={"orientation": "horizontal"}, children=[])
    out = c.emit()
    assert out["type"] == "ia.container.split"
    assert out["props"] == {"orientation": "horizontal"}
    assert "children" not in out
    # Non-empty children still emit (suppression is empty-only).
    from ignition_gen_sdk.models.views.component import Component
    c2 = SplitContainer(props={"orientation": "horizontal"}, children=[
        Component(type="ia.display.label"),
    ])
    assert c2.emit()["children"][0]["type"] == "ia.display.label"
