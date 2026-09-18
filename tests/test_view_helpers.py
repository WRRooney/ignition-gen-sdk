"""Tests for view helper models (the 3 helpers we ship).

Helpers shipped: Meta, Tooltip, Icon.
Helpers explicitly NOT shipped:
Style (DROP — use plain dict[str, Any]), Label / Point / ContextMenu /
EmbeddedView / Pipe (deferred).
"""
from __future__ import annotations

import pydantic
import pytest

from ignition_gen_sdk.models.views.icon import Icon
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.tooltip import Tooltip


# ---- Tooltip ----

def test_tooltip_text_only():
    """Verified live shape: 36/36 samplequickstart Tooltips set only `text`."""
    t = Tooltip(text="Hello")
    assert t.model_dump(exclude_none=True, mode="json") == {"text": "Hello"}


def test_tooltip_all_optional_emit_empty():
    """Default Tooltip() has all None fields → emit() == {}."""
    assert Tooltip().model_dump(exclude_none=True, mode="json") == {}


def test_tooltip_full_fields_emit():
    t = Tooltip(text="Hi", enabled=True, width="200px", delay=500)
    out = t.model_dump(exclude_none=True, mode="json")
    assert out == {"delay": 500, "enabled": True, "text": "Hi", "width": "200px"}


def test_tooltip_extra_forbid():
    with pytest.raises(pydantic.ValidationError):
        Tooltip(unknown="x")  # type: ignore[call-arg]


# ---- Icon ----

def test_icon_path_only():
    assert Icon(path="material/check").model_dump(exclude_none=True, mode="json") == {
        "path": "material/check"
    }


def test_icon_path_and_color():
    out = Icon(path="material/cloud_download", color="#229EF3").model_dump(
        exclude_none=True, mode="json"
    )
    assert out == {"color": "#229EF3", "path": "material/cloud_download"}


def test_icon_empty_emit():
    assert Icon().model_dump(exclude_none=True, mode="json") == {}


def test_icon_extra_forbid():
    with pytest.raises(pydantic.ValidationError):
        Icon(badfield="x")  # type: ignore[call-arg]


# ---- Meta integration with the real Tooltip module ----

def test_meta_with_tooltip():
    """Meta now imports Tooltip from tooltip.py (not an in-file stub)."""
    m = Meta(name="X", tooltip=Tooltip(text="Hover me"))
    out = m.emit()
    assert out == {"name": "X", "tooltip": {"text": "Hover me"}}


def test_meta_tooltip_none_omitted():
    m = Meta(name="X")
    assert "tooltip" not in m.emit()


def test_meta_imports_tooltip_from_dedicated_module():
    """Sanity check: Meta's Tooltip is the same class as the one in tooltip.py."""
    from ignition_gen_sdk.models.views import meta as meta_module
    from ignition_gen_sdk.models.views.tooltip import Tooltip as DedicatedTooltip
    assert meta_module.Tooltip is DedicatedTooltip


# ---- default-factory isolation ----

def test_meta_name_uniqueness_still_holds_after_helper_extraction():
    """Editing meta.py must not regress the default-factory fix."""
    metas = [Meta() for _ in range(100)]
    assert len({m.name for m in metas}) == 100


# ---- Public API ----

def test_helpers_importable_from_views_package():
    from ignition_gen_sdk.models.views import Meta as M, Tooltip as T, Icon as I  # noqa: F401


# embedded_view view_params= typo trap guard
def test_embedded_view_rejects_snake_case_view_params():
    """view_params= (snake, mirroring view_path=) is the natural wrong guess;
    it would silently become a junk prop (extra=allow) and the embed gets no
    params. embedded_view must raise a helpful error pointing to params=."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    with pytest.raises(ValueError) as ei:
        ViewBuilder().coord_root().embedded_view(
            view_path="Components/Symbols/Pump", view_params={"tagPath": "X/Y"})
    assert "params" in str(ei.value)


def test_embedded_view_params_works():
    from ignition_gen_sdk.builders.view import ViewBuilder
    c = ViewBuilder().coord_root().embedded_view(
        view_path="Components/Symbols/Pump", params={"tagPath": "X/Y"})
    assert c.props.params == {"tagPath": "X/Y"}
    assert c.props.path == "Components/Symbols/Pump"


def test_embedded_view_serializes_params_not_viewparams():
    """Locking test: the serialized JSON key is 'params', never 'viewParams'."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    c = ViewBuilder().coord_root().embedded_view(
        view_path="Components/Symbols/Pump", params={"tagPath": "X/Y"})
    dumped = c.model_dump(exclude_none=True, mode="json")
    assert dumped["props"]["params"] == {"tagPath": "X/Y"}
    assert "viewParams" not in dumped["props"]


def test_embedded_view_rejects_stale_viewparams_kwarg():
    """viewParams was the old field name; must raise, not ride as junk."""
    import pytest
    from ignition_gen_sdk.builders.view import ViewBuilder
    with pytest.raises(ValueError, match="viewParams"):
        ViewBuilder().coord_root().embedded_view(
            view_path="Components/Symbols/Pump", viewParams={"tagPath": "X"})


# generalized snake_case-typo guard across factories
def test_label_rejects_snake_case_of_camel_prop():
    from ignition_gen_sdk.builders.view import ViewBuilder
    with pytest.raises(ValueError) as ei:
        ViewBuilder().flex_root().label(text="x", align_vertical="center")
    assert "alignVertical" in str(ei.value)


def test_factory_accepts_genuinely_extra_underscore_prop():
    """A snake_case key whose camelCase is NOT a model field is a legit extra
    prop (extra='allow') and must pass — no false positive."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    c = ViewBuilder().flex_root().label(text="x", data_foo="bar")
    assert getattr(c.props, "data_foo", None) == "bar" or c.props.model_dump().get("data_foo") == "bar"


def test_reject_snake_case_typos_helper_direct():
    from ignition_gen_sdk.builders.view import _reject_snake_case_typos
    from ignition_gen_sdk.models.views.components.embedding import EmbeddedViewProps
    # camelCase field typed snake -> raise
    with pytest.raises(ValueError):
        _reject_snake_case_typos({"use_default_view_height": True}, EmbeddedViewProps)
    # exact field -> ok; unrelated snake -> ok
    _reject_snake_case_typos({"params": {}}, EmbeddedViewProps)
    _reject_snake_case_typos({"totally_custom": 1}, EmbeddedViewProps)


def test_bind_expression_emits_persistent_and_access_flags():
    """Designer-authored views: position.display expr bindings carry
    `persistent: true` beside the binding; bind_expression must emit the
    entry-level flags the same way bind_property does."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    c = ViewBuilder().flex_root().label(text="x")
    c.bind_expression("position.display", "len({view.params.note}) > 0", persistent=True)
    c.bind_expression("props.enabled", "{view.custom.ok}", access="PROTECTED")
    d = c.model_dump(exclude_none=True, mode="json")["propConfig"]
    assert d["position.display"]["persistent"] is True
    assert d["position.display"]["binding"]["type"] == "expr"
    assert d["props.enabled"]["access"] == "PROTECTED"
    assert "persistent" not in d["props.enabled"]


def test_drop_udt_emits_designer_drop_config_and_model_guards_shape():
    """`props.dropConfig.udts[]` on a UDT tile view: dropping a UDT instance on a container embeds the tile with
    `tagPath` = the instance path. Shape per Designer ground truth."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    from ignition_gen_sdk.models.views.view import View
    vb = ViewBuilder(); vb.flex_root(); vb.params(tagPath="")
    vb.drop_udt("Equipment/Motor")
    d = vb.build().model_dump(exclude_none=True, mode="json")
    assert d["props"]["dropConfig"] == {
        "udts": [{"action": "path", "param": "tagPath", "type": "Equipment/Motor"}]}
    with pytest.raises(ValueError):
        View.model_validate({"root": {"type": "ia.container.flex", "meta": {"name": "root"}},
                             "props": {"dropConfig": {"udts": [{"type": "Equipment/Motor"}]}}})
