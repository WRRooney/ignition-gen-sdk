"""Tests for the ViewBuilder (Flex subset + Flex positions)."""
from __future__ import annotations

import pytest

from ignition_gen_sdk.builders.view import ViewBuilder
from ignition_gen_sdk.models.views.component import Component
from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.positions import FlexChildPosition
from ignition_gen_sdk.models.views.view import View


def test_flex_root_returns_self():
    b = ViewBuilder()
    assert b.flex_root() is b


def test_add_to_flex_returns_self():
    b = ViewBuilder().flex_root()
    assert b.add_to_flex(Component(type="ia.display.label")) is b


def test_build_without_root_raises():
    with pytest.raises(ValueError) as exc_info:
        ViewBuilder().build()
    assert "root" in str(exc_info.value).lower()


def test_minimal_flex_view_builds():
    v = (ViewBuilder()
         .flex_root(direction="column")
         .add_to_flex(Component(type="ia.display.label", meta=Meta(name="Hello"), props={"text": "Hello"}))
         .build())
    assert isinstance(v, View)
    assert isinstance(v.root, FlexContainer)
    assert v.root.props == {"direction": "column"}
    assert len(v.root.children) == 1
    assert v.root.children[0].type == "ia.display.label"


def test_add_to_flex_with_position(tmp_path):
    """Builder applies FlexChildPosition.model_dump correctly."""
    label = Component(type="ia.display.label", meta=Meta(name="Hi"), props={"text": "Hi"})
    v = (ViewBuilder()
         .flex_root()
         .add_to_flex(label, position=FlexChildPosition(basis="56px", shrink=0))
         .build())
    assert v.root.children[0].position == {"basis": "56px", "shrink": 0}


def test_add_to_flex_no_position_keeps_none():
    """position=None (default) must NOT become {}."""
    label = Component(type="ia.display.label")
    v = ViewBuilder().flex_root().add_to_flex(label).build()
    assert v.root.children[0].position is None


def test_add_to_flex_wrong_root_type_raises():
    """Manually set non-Flex root, then add_to_flex should TypeError."""
    b = ViewBuilder()
    b._root = Component(type="ia.container.coord")  # type: ignore[assignment]
    with pytest.raises(TypeError) as exc_info:
        b.add_to_flex(Component(type="ia.display.label"))
    assert "flex_root" in str(exc_info.value)
