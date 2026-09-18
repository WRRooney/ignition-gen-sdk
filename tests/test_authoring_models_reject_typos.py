"""Regression lock — the tag-authoring models REJECT unknown keys.

Unlike the view-component Props (extra="allow" — a forward-compat choice that
made snake_case prop typos silent until the snake_case guard), the tag-side authoring
models inherit IgnitionBaseModel's `extra="forbid"`, so a typo'd key (e.g.
`value_source` for `valueSource`) raises loudly at author time. This locks that
property: a future refactor flipping one of these to extra="allow" would
silently reintroduce the typo trap on the framework's PRIMARY user input (tags)
— and fail this test instead.
"""
from __future__ import annotations

import pydantic
import pytest

from ignition_gen_sdk.models.tags.alarm import Alarm
from ignition_gen_sdk.models.tags.tag import Tag
from ignition_gen_sdk.models.tags.udt import UdtType
from ignition_gen_sdk.models.views.positions import (
    CoordinatePosition,
    FlexChildPosition,
)

_FORBID_MODELS = [Tag, Alarm, CoordinatePosition, FlexChildPosition]


@pytest.mark.parametrize("model_cls", _FORBID_MODELS)
def test_authoring_model_forbids_extra(model_cls):
    assert model_cls.model_config.get("extra") == "forbid", (
        f"{model_cls.__name__} must be extra='forbid' so key typos are rejected, "
        f"not silently kept"
    )


def test_udt_type_allows_only_meta_prefixed_extras():
    # UdtType is extra='allow' to carry the flat meta_* custom-prop layer
    # (default/Field ground truth), but a validator restricts extras to the
    # meta_ prefix — so the typo trap stays closed for every other key.
    ut = UdtType(name="X", typeId="_Global", meta_view="Field/Input/X")
    assert ut.model_dump(exclude_none=True)["meta_view"] == "Field/Input/X"
    with pytest.raises(pydantic.ValidationError):
        UdtType(name="X", type_id="_Global")  # typeId typo still rejected


def test_tag_rejects_snake_case_key_typo():
    with pytest.raises(pydantic.ValidationError):
        Tag(name="t", tagType="AtomicTag", value_source="memory")  # valueSource typo


def test_alarm_rejects_unknown_key():
    with pytest.raises(pydantic.ValidationError):
        Alarm(name="HiHi", set_point_a=90.0)  # setpointA typo


def test_valid_keys_still_accepted():
    # Sanity: the correct camelCase keys construct fine.
    t = Tag(name="t", tagType="AtomicTag", dataType="Float8", valueSource="memory", value=1.0)
    assert t.valueSource == "memory"
