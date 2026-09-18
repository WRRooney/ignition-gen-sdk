"""Tests for the Meta model."""
from __future__ import annotations

from ignition_gen_sdk.models.views.meta import Meta


def test_meta_name_default_factory_unique():
    """100 Meta() instances must have 100 distinct name values."""
    metas = [Meta() for _ in range(100)]
    names = {m.name for m in metas}
    assert len(names) == 100, f"Got {len(names)} unique names from 100 instances"


def test_meta_name_default_format():
    """Default name follows component_<8hex> pattern."""
    m = Meta()
    assert m.name.startswith("component_")
    assert len(m.name) == len("component_") + 8


def test_meta_explicit_name_emits():
    m = Meta(name="MyButton")
    assert m.emit() == {"name": "MyButton"}


def test_meta_optional_fields_omitted_when_none():
    m = Meta(name="X")
    out = m.emit()
    assert "hasDelegate" not in out
    assert "visible" not in out
    assert "tooltip" not in out


def test_meta_explicit_hasDelegate_emits():
    m = Meta(name="X", hasDelegate=True)
    assert m.emit() == {"hasDelegate": True, "name": "X"}
