"""Tests for full Tag 8.3 schema coverage.

Verifies the Tag model has every 8.3-only field added, fixes the renamed
Literals (`Analog_Compressed`, `MONTH`), introduces a distinct `defaultValue`
field, and emits no null keys for a richly-populated tag.
"""
from __future__ import annotations

import pydantic
import pytest

from ignition_gen_sdk.models.tags.alarm import Alarm
from ignition_gen_sdk.models.tags.enums.tag_alarm_mode import TagAlarmMode
from ignition_gen_sdk.models.tags.enums.tag_alarm_priority import TagAlarmPriority
from ignition_gen_sdk.models.tags.tag import Tag


# --- 8.3-only fields accepted and emitted -----------------------------------


def test_value_persistence_accepted_and_emits():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        valuePersistence="Database",
    )
    assert t.emit()["valuePersistence"] == "Database"


def test_history_time_deadband_units_accepted():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        historyTimeDeadbandUnits="MONTH",
    )
    assert t.emit()["historyTimeDeadbandUnits"] == "MONTH"


def test_history_max_age_and_units_emit():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        historyMaxAge=30.0,
        historyMaxAgeUnits="DAY",
    )
    d = t.emit()
    assert d["historyMaxAge"] == 30.0
    assert d["historyMaxAgeUnits"] == "DAY"


def test_max_time_between_samples_emit():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        maxTimeBetweenSamples=5.0,
        maxTimeBetweenSamplesUnits="MIN",
    )
    d = t.emit()
    assert d["maxTimeBetweenSamples"] == 5.0
    assert d["maxTimeBetweenSamplesUnits"] == "MIN"


def test_preserve_source_timestamp_accepted():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="Derived",
        preserveSourceTimestamp=True,
    )
    assert t.emit()["preserveSourceTimestamp"] is True


# --- Literal-rename fixes ---------------------------------------------------


def test_history_sample_rate_units_month_valid():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        historySampleRateUnits="MONTH",
    )
    assert t.emit()["historySampleRateUnits"] == "MONTH"


def test_history_sample_rate_units_mon_rejected():
    with pytest.raises(pydantic.ValidationError):
        Tag(
            name="T",
            tagType="AtomicTag",
            dataType="Float8",
            valueSource="memory",
            historySampleRateUnits="MON",
        )


def test_historical_deadband_style_compressed_valid():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        historicalDeadbandStyle="Analog_Compressed",
    )
    assert t.emit()["historicalDeadbandStyle"] == "Analog_Compressed"


def test_historical_deadband_style_analog_rejected():
    with pytest.raises(pydantic.ValidationError):
        Tag(
            name="T",
            tagType="AtomicTag",
            dataType="Float8",
            valueSource="memory",
            historicalDeadbandStyle="Analog",
        )


# --- defaultValue / value distinction ---------------------------------------


def test_default_value_emits_when_value_is_none():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        defaultValue=0.0,
    )
    d = t.emit()
    assert "defaultValue" in d
    assert d["defaultValue"] == 0.0
    assert "value" not in d


def test_value_emits_when_default_value_is_none():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        value=42.0,
    )
    d = t.emit()
    assert "value" in d
    assert d["value"] == 42.0
    assert "defaultValue" not in d


def test_both_value_and_default_value_can_coexist():
    t = Tag(
        name="T",
        tagType="AtomicTag",
        dataType="Float8",
        valueSource="memory",
        value=42.0,
        defaultValue=0.0,
    )
    d = t.emit()
    assert d["value"] == 42.0
    assert d["defaultValue"] == 0.0


# --- Recursive forward-ref still works --------------------------------------


def test_recursive_tags_still_works_after_field_additions():
    """Tag.model_rebuild() must remain in place; recursive tag trees emit."""
    parent = Tag(
        name="Folder",
        tagType="Folder",
        dataType="Float8",
        valueSource="memory",
        tags=[
            Tag(
                name="Child",
                tagType="AtomicTag",
                dataType="Float8",
                valueSource="memory",
            )
        ],
    )
    d = parent.emit()
    assert d["tags"][0]["name"] == "Child"


# --- Full rich tag emit has no null keys ------------------------------------


def test_full_tag_with_alarms_history_opc_no_null_keys():
    a = Alarm(
        name="Hi",
        mode=TagAlarmMode.ABOVE_SETPOINT,
        priority=TagAlarmPriority.CRITICAL,
        setpointA=90.0,
        displayPath="Level Hi Alarm",
        notes="Level is too high",
    )
    t = Tag(
        name="WriteableInteger1",
        tagType="AtomicTag",
        dataType="Int4",
        valueSource="opc",
        opcItemPath="ns=1;s=[Sample_Device]_Meta:Writeable/WriteableInteger1",
        opcServer="Ignition OPC UA Server",
        alarms=[a],
        historyEnabled=True,
        historyProvider="Sample_SQLite_Database",
        historicalDeadband=0.1,
        historicalDeadbandStyle="Analog_Compressed",
        historySampleRateUnits="MONTH",
        historyTimeDeadband=2.0,
        historyTimeDeadbandUnits="SEC",
        historyMaxAge=30.0,
        historyMaxAgeUnits="DAY",
        maxTimeBetweenSamples=5.0,
        maxTimeBetweenSamplesUnits="MIN",
        valuePersistence="Database",
        defaultValue=0,
    )
    d = t.emit()
    # No null values anywhere at top level
    assert all(v is not None for v in d.values()), f"null values found: {d}"
    # Alarms still nested correctly
    assert d["alarms"][0]["mode"] == "AboveValue"
    assert d["alarms"][0]["priority"] == "Critical"


def test_history_max_age_preserves_int_vs_float():
    """Designer writes `historyMaxAge: 1` (int); a float-only field re-emitted `1.0`
    on every ign udt-type write. Preserve the input kind."""
    from ignition_gen_sdk.models.tags.tag import Tag
    base = {"name": "t", "tagType": "AtomicTag", "dataType": "Int4", "valueSource": "memory"}
    assert Tag.model_validate({**base, "historyMaxAge": 1}).model_dump(exclude_none=True)["historyMaxAge"] == 1
    assert isinstance(Tag.model_validate({**base, "historyMaxAge": 1}).historyMaxAge, int)
    assert isinstance(Tag.model_validate({**base, "historyMaxAge": 1.5}).historyMaxAge, float)
