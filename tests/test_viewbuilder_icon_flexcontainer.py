"""Tests for ViewBuilder.icon() and ViewBuilder.flex_container() factory methods.

icon() — ia.display.icon component factory
flex_container() — standalone child FlexContainer factory
"""
from __future__ import annotations


from ignition_gen_sdk.builders.view import ViewBuilder
from ignition_gen_sdk.models.views.component import Component
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.view import View
from ignition_gen_sdk.serializers.view_disk import view_to_disk


# ---------------------------------------------------------------------------
# ViewBuilder.icon()
# ---------------------------------------------------------------------------

def test_icon_returns_icon_type():
    """icon() returns component with type='ia.display.icon'."""
    vb = ViewBuilder()
    icon = vb.icon(name="AlarmMarker", path="material/alarm")
    assert icon.type == "ia.display.icon"


def test_icon_props_path():
    """Returned Icon has props.path == passed path."""
    vb = ViewBuilder()
    icon = vb.icon(name="AlarmMarker", path="material/alarm")
    assert icon.props.path == "material/alarm"


def test_icon_auto_attaches_to_flex_root():
    """With a flex root set, icon() auto-attaches to root.children."""
    vb = ViewBuilder()
    vb.flex_root()
    vb.icon(name="AlarmMarker", path="material/alarm")
    assert len(vb._root.children) == 1
    assert vb._root.children[0].type == "ia.display.icon"


def test_icon_standalone_no_root():
    """Without a root, icon() returns standalone Icon not attached anywhere."""
    vb = ViewBuilder()
    icon = vb.icon(name="StandaloneIcon", path="material/check")
    assert vb._root is None
    assert icon.type == "ia.display.icon"


def test_icon_extra_props_pass_through():
    """Extra props (color) flow through to IconProps."""
    vb = ViewBuilder()
    icon = vb.icon(name="X", path="material/check", color="#ff0000")
    assert icon.props.color == "#ff0000"


def test_icon_view_model_validate_round_trip():
    """View.model_validate(view_to_disk(view)) does not raise with icon in children."""
    vb = ViewBuilder()
    vb.flex_root()
    vb.icon(name="M", path="material/alarm")
    view = vb.build()
    disk = view_to_disk(view)
    validated = View.model_validate(disk)
    root_child = validated.root.children[0]
    assert root_child.type == "ia.display.icon"


# ---------------------------------------------------------------------------
# ViewBuilder.flex_container()
# ---------------------------------------------------------------------------

def test_flex_container_type_and_meta():
    """flex_container() returns FlexContainer with correct type and meta.name."""
    vb = ViewBuilder()
    container = vb.flex_container(name="HeaderRow", direction="row")
    assert container.type == "ia.container.flex"
    assert container.meta.name == "HeaderRow"


def test_flex_container_direction_in_props():
    """Returned FlexContainer has props['direction'] == passed direction."""
    vb = ViewBuilder()
    container = vb.flex_container(name="HeaderRow", direction="row")
    assert container.props["direction"] == "row"


def test_flex_container_empty_children_by_default():
    """Returned FlexContainer has children=[] (empty by default)."""
    vb = ViewBuilder()
    container = vb.flex_container(name="Inner", direction="column")
    assert container.children == []


def test_flex_container_does_not_auto_attach():
    """flex_container does NOT auto-attach to vb._root.children."""
    vb = ViewBuilder()
    vb.flex_root()
    vb.flex_container(name="Inner", direction="row")
    # root.children should still be empty — caller must place it explicitly
    assert len(vb._root.children) == 0


def test_flex_container_children_mutable():
    """container.children.append(...) works — the object is mutable."""
    vb = ViewBuilder()
    container = vb.flex_container(name="Row", direction="row")
    label = Component(
        type="ia.display.label",
        meta=Meta(name="Val"),
        props={"text": "value"},
    )
    container.children.append(label)
    assert len(container.children) == 1
    assert container.children[0].type == "ia.display.label"


def test_flex_container_nested_in_flex_root():
    """vb.flex_root().add_to_flex(vb.flex_container(...)).build() — child[0] is ia.container.flex."""
    vb = ViewBuilder()
    vb.flex_root()
    inner = vb.flex_container(name="Inner", direction="row")
    vb.add_to_flex(inner)
    view = vb.build()
    assert view.root.children[0].type == "ia.container.flex"


def test_flex_container_nested_view_model_validate():
    """View.model_validate round-trip for root-flex -> child-flex -> label does not raise."""
    from ignition_gen_sdk.models.views.components.display import Label, LabelProps

    vb = ViewBuilder()
    vb.flex_root()

    # Build an inner flex container with a label child
    inner = vb.flex_container(name="InnerRow", direction="row")
    inner.children.append(
        Label(
            meta=Meta(name="Val"),
            props=LabelProps(text="value"),
        )
    )
    vb.add_to_flex(inner)

    view = vb.build()
    disk = view_to_disk(view)
    validated = View.model_validate(disk)

    # Verify structure: root -> inner flex -> label
    inner_flex = validated.root.children[0]
    assert inner_flex.type == "ia.container.flex"
    assert inner_flex.children[0].type == "ia.display.label"
