"""Tests locking View.params scalar-only contract.

Perspective view params must be plain scalars, not UdtParameter-shaped dicts.

Caller audit: 0 existing View.params call sites used the UdtParameter shape.
All 'dataType' grep matches were in UDT tag models — correct usage, no fixups needed.
"""
from __future__ import annotations

import pytest
import pydantic

from ignition_gen_sdk.models.views.view import View
from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta


def _flex_root() -> FlexContainer:
    return FlexContainer(meta=Meta(name="root"), props={"direction": "column"}, children=[])


def test_params_plain_string_accepted():
    """Plain string param value accepted and emitted as-is."""
    v = View(root=_flex_root(), params={"tagPath": "[default]Tanks/T01"})
    out = v.emit()
    assert out["params"] == {"tagPath": "[default]Tanks/T01"}


def test_params_none_accepted_pitfall1():
    """None param values survive (Pydantic exclude_none only strips fields, not dict entries)."""
    v = View(root=_flex_root(), params={"TankNo": None})
    out = v.emit()
    assert out["params"]["TankNo"] is None


def test_params_int_float_bool_accepted():
    """Numeric and bool param values accepted."""
    v = View(root=_flex_root(), params={"n": 3, "r": 0.5, "f": True})
    out = v.emit()
    assert out["params"] == {"n": 3, "r": 0.5, "f": True}


def test_params_udt_shape_rejected():
    """UdtParameter-shaped value (has both 'value' and 'dataType' keys) must raise ValidationError."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        View(root=_flex_root(), params={"tagPath": {"value": "", "dataType": "String"}})
    # Error message must name the offending key
    assert "tagPath" in str(exc_info.value)


def test_params_udt_shape_rejected_non_string_value():
    """UdtParameter shape with non-string value also rejected."""
    with pytest.raises(pydantic.ValidationError):
        View(root=_flex_root(), params={"n": {"value": 42, "dataType": "Int4"}})


def test_params_dict_without_both_keys_passes():
    """Dict param value that lacks both 'value' AND 'dataType' keys is allowed."""
    v = View(root=_flex_root(), params={"meta": {"label": "hello"}})
    out = v.emit()
    assert out["params"] == {"meta": {"label": "hello"}}


def test_params_empty_accepted():
    """Empty params dict accepted."""
    v = View(root=_flex_root(), params={})
    out = v.emit()
    assert "params" in out
    assert out["params"] == {}
