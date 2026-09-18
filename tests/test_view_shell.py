"""Tests for the View top-level shape."""
from __future__ import annotations

from ignition_gen_sdk.models.views.view import View
from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta


def _flex_root() -> FlexContainer:
    return FlexContainer(meta=Meta(name="root"), props={"direction": "column"}, children=[])


def test_view_top_level_keys_minimal():
    """Minimal view emits exactly {custom, params, props, root}."""
    v = View(root=_flex_root())
    out = v.emit()
    assert set(out.keys()) == {"custom", "params", "props", "root"}


def test_view_propConfig_emitted_when_set():
    v = View(root=_flex_root(), propConfig={"params.x": {"paramDirection": "input"}})
    out = v.emit()
    assert "propConfig" in out
    assert out["propConfig"] == {"params.x": {"paramDirection": "input"}}


def test_view_propConfig_omitted_when_none():
    v = View(root=_flex_root())
    assert "propConfig" not in v.emit()


def test_view_events_omitted_when_none():
    v = View(root=_flex_root())
    assert "events" not in v.emit()


def test_view_params_preserves_nested_null_values():
    """View.params={'x': None} must keep ``"x": None`` in emit output.
    exclude_none strips Pydantic FIELDS, not nested dict ENTRIES.
    """
    v = View(root=_flex_root(), params={"TankNo": None})
    out = v.emit()
    assert out["params"] == {"TankNo": None}


def test_view_no_top_level_scripts_field():
    """View has no top-level ``scripts`` field — a common typo to guard against."""
    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        View(root=_flex_root(), scripts={"foo": "bar"})  # type: ignore[call-arg]


def test_view_permissions_roundtrip():
    """Designer view-permissions gate must survive load -> emit."""
    perms = {
        "type": "AnyOf",
        "securityLevels": [{"children": [], "name": "Authenticated"}],
    }
    v = View(root=_flex_root(), permissions=perms)
    out = v.emit()
    assert out["permissions"] == perms


def test_view_permissions_omitted_when_none():
    v = View(root=_flex_root())
    assert "permissions" not in v.emit()
