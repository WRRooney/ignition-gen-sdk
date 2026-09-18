"""Tests for ViewBuilder fan-out across all 6 containers."""
from __future__ import annotations

import pytest

from ignition_gen_sdk.builders.view import ViewBuilder
from ignition_gen_sdk.models.views.component import Component
from ignition_gen_sdk.models.views.containers import (
    BreakpointContainer,
    ColumnContainer,
    CoordinateContainer,
    FlexContainer,
    SplitContainer,
    TabContainer,
    TabSpec,
)
from ignition_gen_sdk.models.views.positions import (
    ColumnBreakpoint,
    ColumnChildPosition,
    CoordinatePosition,
)
import pydantic


def _label(name: str = "L") -> Component:
    from ignition_gen_sdk.models.views.meta import Meta
    return Component(type="ia.display.label", meta=Meta(name=name), props={"text": name})


# ---- Each _root() returns Self and produces the right container type ----

def test_coord_root_returns_self_and_correct_type():
    b = ViewBuilder()
    assert b.coord_root() is b
    assert isinstance(b._root, CoordinateContainer)


def test_split_root_returns_self_and_correct_type():
    b = ViewBuilder()
    assert b.split_root() is b
    assert isinstance(b._root, SplitContainer)


def test_tab_root_returns_self_and_correct_type():
    b = ViewBuilder()
    assert b.tab_root() is b
    assert isinstance(b._root, TabContainer)


def test_breakpoint_root_returns_self_and_correct_type():
    b = ViewBuilder()
    assert b.breakpoint_root() is b
    assert isinstance(b._root, BreakpointContainer)


def test_column_root_returns_self_and_correct_type():
    b = ViewBuilder()
    assert b.column_root() is b
    assert isinstance(b._root, ColumnContainer)


# ---- Each add_to_*() applies the correct position shape ----

def test_add_to_coord_applies_coordinate_position():
    label = _label()
    v = (ViewBuilder()
         .coord_root(mode="percent")
         .add_to_coord(label, position=CoordinatePosition(x=10, y=66, width=180, height=80))
         .build())
    assert v.root.children[0].position == {"x": 10, "y": 66, "width": 180, "height": 80}


def test_add_to_split_applies_side():
    label = _label()
    v = ViewBuilder().split_root().add_to_split(label, side="left").build()
    assert v.root.children[0].position == {"position": "left"}


def test_add_to_tab_applies_tab_index():
    label = _label()
    v = (ViewBuilder()
         .tab_root(tabs=["A", "B"])
         .add_to_tab(label, tab_index=0)
         .build())
    assert v.root.children[0].position == {"tabIndex": 0}


def test_add_to_breakpoint_applies_size():
    label = _label()
    v = (ViewBuilder()
         .breakpoint_root(breakpoint=900)
         .add_to_breakpoint(label, size="large")
         .build())
    assert v.root.children[0].position == {"size": "large"}


def test_add_to_column_applies_breakpoints():
    label = _label()
    bps = [{"colIndex": 0, "name": "sm", "order": 1, "rowIndex": 0, "span": 12}]
    v = (ViewBuilder()
         .column_root()
         .add_to_column(label, breakpoints=bps, height=80)
         .build())
    assert v.root.children[0].position == {"breakpoints": bps, "height": 80}


# ---- Wrong-root-type guards (TypeError) ----

def test_add_to_coord_wrong_root_raises():
    b = ViewBuilder().flex_root()
    with pytest.raises(TypeError) as exc_info:
        b.add_to_coord(_label())
    assert "coord_root" in str(exc_info.value)


def test_add_to_split_wrong_root_raises():
    b = ViewBuilder().flex_root()
    with pytest.raises(TypeError):
        b.add_to_split(_label(), side="left")


def test_add_to_tab_wrong_root_raises():
    b = ViewBuilder().flex_root()
    with pytest.raises(TypeError):
        b.add_to_tab(_label(), tab_index=0)


def test_add_to_breakpoint_wrong_root_raises():
    b = ViewBuilder().flex_root()
    with pytest.raises(TypeError):
        b.add_to_breakpoint(_label(), size="large")


def test_add_to_column_wrong_root_raises():
    b = ViewBuilder().flex_root()
    with pytest.raises(TypeError):
        b.add_to_column(_label(), height=80)


# ---- Position=None still works ----

def test_add_to_split_no_side_keeps_position_none():
    label = _label()
    v = ViewBuilder().split_root().add_to_split(label).build()
    assert v.root.children[0].position is None


def test_add_to_column_no_kwargs_keeps_position_none():
    label = _label()
    v = ViewBuilder().column_root().add_to_column(label).build()
    assert v.root.children[0].position is None


# ---- Each chain builds a valid View ----

def test_all_6_containers_build_a_view():
    """Every container's full chain produces a View whose root is the right type."""
    cases = [
        (ViewBuilder().flex_root().add_to_flex(_label()), FlexContainer, "ia.container.flex"),
        (ViewBuilder().coord_root().add_to_coord(_label()), CoordinateContainer, "ia.container.coord"),
        (ViewBuilder().split_root().add_to_split(_label(), side="left"), SplitContainer, "ia.container.split"),
        (ViewBuilder().tab_root().add_to_tab(_label(), tab_index=0), TabContainer, "ia.container.tab"),
        (ViewBuilder().breakpoint_root().add_to_breakpoint(_label(), size="large"), BreakpointContainer, "ia.container.breakpt"),
        (ViewBuilder().column_root().add_to_column(_label(), height=80), ColumnContainer, "ia.container.column"),
    ]
    for builder, expected_cls, expected_type in cases:
        view = builder.build()
        assert isinstance(view.root, expected_cls), f"Got {type(view.root).__name__}"
        assert view.root.type == expected_type
        assert len(view.root.children) == 1


# ---- add_to_* idempotency: auto-attaching factory + add_to_* ----
# The element factories (label/icon/...) AUTO-ATTACH to the current root.
# `add_to_<container>(vb.label(...), ...)` must NOT attach the same object a
# second time (the breakpt/split/tab/column duplicate-child trap).

def test_add_to_breakpoint_idempotent_with_auto_attaching_factory():
    vb = ViewBuilder().breakpoint_root(breakpoint=900)
    vb.add_to_breakpoint(vb.label(text="small view"), size="small")
    vb.add_to_breakpoint(vb.label(text="large view"), size="large")
    kids = vb.build().root.children
    assert len(kids) == 2, "factory auto-attach + add_to_breakpoint duplicated children"
    assert [k.position for k in kids] == [{"size": "small"}, {"size": "large"}]
    assert [k.props.text for k in kids] == ["small view", "large view"]


@pytest.mark.parametrize("setup", [
    lambda vb: (vb.flex_root(), vb.add_to_flex(vb.label(text="x"))),
    lambda vb: (vb.coord_root(), vb.add_to_coord(vb.label(text="x"))),
    lambda vb: (vb.split_root(), vb.add_to_split(vb.label(text="x"), side="left")),
    lambda vb: (vb.tab_root(), vb.add_to_tab(vb.label(text="x"), tab_index=0)),
    lambda vb: (vb.breakpoint_root(), vb.add_to_breakpoint(vb.label(text="x"), size="large")),
    lambda vb: (vb.column_root(), vb.add_to_column(vb.label(text="x"), height=80)),
])
def test_all_add_to_helpers_idempotent_for_factory_children(setup):
    vb = ViewBuilder()
    setup(vb)
    assert len(vb.build().root.children) == 1


def test_add_to_breakpoint_standalone_component_still_appends_once():
    # The original pattern (a bare, non-attached component) is unchanged.
    vb = ViewBuilder().breakpoint_root()
    vb.add_to_breakpoint(_label("solo"), size="large")
    assert len(vb.build().root.children) == 1


def test_add_to_flex_distinct_equal_components_not_collapsed():
    # Identity de-dup, NOT ==: two distinct field-equal labels both attach.
    vb = ViewBuilder().flex_root()
    vb.add_to_flex(_label("dup"))
    vb.add_to_flex(_label("dup"))
    assert len(vb.build().root.children) == 2


# ---- tab_root object-form tabs via TabSpec ----
# Ground truth: samplequickstart Containers/Tab uses object form
# [{disabled, text}, ...]; IndustryPack-DataCenter Overview uses a bare string
# array. tab_root accepts both; TabSpec makes per-tab disabled/icon typed.

def test_tab_root_objectform_emits_text_and_disabled():
    vb = ViewBuilder().tab_root(tabs=[
        TabSpec(text="Tab 1"),
        TabSpec(text="Tab 3", disabled=True),
    ])
    tabs = vb.build().root.props["tabs"]
    # disabled is ALWAYS emitted (matches the gateway sample, even when false)
    assert tabs == [
        {"text": "Tab 1", "disabled": False},
        {"text": "Tab 3", "disabled": True},
    ]


def test_tab_root_objectform_icon_optional():
    vb = ViewBuilder().tab_root(tabs=[
        TabSpec(text="Plain"),
        TabSpec(text="Iconed", icon={"library": "material", "path": "home"}),
    ])
    tabs = vb.build().root.props["tabs"]
    assert "icon" not in tabs[0]
    assert tabs[1]["icon"] == {"library": "material", "path": "home"}


def test_tab_root_mixed_str_and_tabspec():
    vb = ViewBuilder().tab_root(tabs=["Bare", TabSpec(text="Rich", disabled=True)])
    tabs = vb.build().root.props["tabs"]
    assert tabs[0] == "Bare"
    assert tabs[1] == {"text": "Rich", "disabled": True}


def test_tab_root_string_array_backward_compatible():
    # The original string-only form still passes through unchanged.
    vb = ViewBuilder().tab_root(tabs=["Widgets And Faceplates", "Comtrade Dashboard"])
    assert vb.build().root.props["tabs"] == ["Widgets And Faceplates", "Comtrade Dashboard"]


# ---- column breakpoints typed via ColumnBreakpoint ----
# Ground truth: 111/111 column-child breakpoints across 230 IA views have
# exactly {colIndex, name, order, rowIndex, span}. ColumnBreakpoint types it;
# dicts still coerce (back-compat) AND now validate (extra="forbid").
_BP = {"colIndex": 0, "name": "sm", "order": 1, "rowIndex": 0, "span": 12}


def test_add_to_column_typed_breakpoint_emits_five_keys():
    vb = ViewBuilder().column_root()
    vb.add_to_column(_label(), breakpoints=[ColumnBreakpoint(**_BP)], height=80)
    pos = vb.build().root.children[0].position
    assert pos == {"breakpoints": [_BP], "height": 80}


def test_add_to_column_dict_breakpoint_backward_compatible():
    vb = ViewBuilder().column_root()
    vb.add_to_column(_label(), breakpoints=[dict(_BP)])
    assert vb.build().root.children[0].position == {"breakpoints": [_BP]}


def test_add_to_column_mixed_typed_and_dict_breakpoints():
    vb = ViewBuilder().column_root()
    other = {"colIndex": 1, "name": "lg", "order": 2, "rowIndex": 0, "span": 6}
    vb.add_to_column(_label(), breakpoints=[ColumnBreakpoint(**_BP), other])
    assert vb.build().root.children[0].position == {"breakpoints": [_BP, other]}


def test_column_breakpoint_rejects_typoed_key():
    # Was silently accepted when breakpoints were untyped list[dict].
    with pytest.raises(pydantic.ValidationError):
        ColumnChildPosition(breakpoints=[{**_BP, "colIndex": None} | {"colIdx": 0}])


def test_column_breakpoint_requires_all_five_keys():
    with pytest.raises(pydantic.ValidationError):
        ColumnBreakpoint(colIndex=0, name="sm", order=1)  # missing rowIndex, span
