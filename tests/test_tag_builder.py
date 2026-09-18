"""Tests for the TagBuilder fluent DSL.

These tests define the contract for ``ignition_gen_sdk.builders.tag_builder.TagBuilder``:
- Plain Python class (not a Pydantic model).
- Setters return ``Self`` for chain-ability.
- ``build()`` constructs a ``Tag`` via ``Tag(**self._data)`` — Pydantic validates here.
- ``opc()`` sets valueSource=opc, opcItemPath, and (default) opcServer.
- ``memory()`` sets valueSource=memory; emits no opcServer key.
- ``alarm()`` appends to the alarms list.
- ``history(provider, deadband)`` sets historyEnabled=True + provider + deadband.
- Missing required fields → pydantic.ValidationError.
"""
from __future__ import annotations

import pytest
import pydantic

from ignition_gen_sdk.builders.tag_builder import TagBuilder
from ignition_gen_sdk.models.tags.alarm import Alarm
from ignition_gen_sdk.models.tags.tag import Tag
from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
from ignition_gen_sdk.models.tags.enums.tag_alarm_mode import TagAlarmMode
from ignition_gen_sdk.models.tags.enums.tag_alarm_priority import TagAlarmPriority
from ignition_gen_sdk.models.tags.enums.tag_type import TagType


# ---------- Identity / chain semantics ----------


def test_setters_return_self_for_chaining():
    b = TagBuilder()
    assert b.name("T1") is b
    assert b.datatype(TagDataType.DOUBLE) is b
    assert b.memory() is b
    assert b.tag_group("G") is b
    assert b.enabled(True) is b
    assert b.tag_type(TagType.ATOMIC) is b


def test_build_returns_tag_instance():
    t = (
        TagBuilder()
        .name("T1")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .build()
    )
    assert isinstance(t, Tag)


# ---------- OPC tag ----------


def test_opc_chain_emits_correct_fields():
    t = (
        TagBuilder()
        .name("TestLevel")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=[Sample_Device]_Meta:Sine/Sine1")
        .build()
    )
    d = t.emit()
    assert d["name"] == "TestLevel"
    assert d["tagType"] == "AtomicTag"
    assert d["dataType"] == "Float8"
    assert d["valueSource"] == "opc"
    assert d["opcItemPath"] == "ns=1;s=[Sample_Device]_Meta:Sine/Sine1"
    assert "opcServer" in d  # default server populated


def test_opc_default_server_is_ignition_opc_ua_server():
    t = (
        TagBuilder()
        .name("X")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .build()
    )
    assert t.opcServer == "Ignition OPC UA Server"


def test_opc_explicit_server_overrides_default():
    t = (
        TagBuilder()
        .name("X")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test", server="MyOtherServer")
        .build()
    )
    assert t.opcServer == "MyOtherServer"


# ---------- Memory tag ----------


def test_memory_chain_with_default_value_no_opc_server():
    t = (
        TagBuilder()
        .name("MemTag")
        .datatype(TagDataType.FLOAT)
        .memory()
        .default_value(0.0)
        .build()
    )
    d = t.emit()
    assert d["valueSource"] == "memory"
    assert d["defaultValue"] == 0.0
    # default_value is distinct from value
    assert "value" not in d
    # memory tag must not leak opcServer
    assert "opcServer" not in d


def test_value_setter_distinct_from_default_value():
    t = (
        TagBuilder()
        .name("V")
        .datatype(TagDataType.INTEGER)
        .memory()
        .value(42)
        .build()
    )
    d = t.emit()
    assert d["value"] == 42
    assert "defaultValue" not in d


# ---------- Alarm + history ----------


def test_alarm_appended_and_history_set():
    alarm = Alarm(
        name="Hi",
        mode=TagAlarmMode.ABOVE_SETPOINT,
        priority=TagAlarmPriority.CRITICAL,
        setpointA=90.0,
    )
    t = (
        TagBuilder()
        .name("Level")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .alarm(alarm)
        .history(provider="default", deadband=0.1)
        .build()
    )
    d = t.emit()
    assert "alarms" in d
    assert len(d["alarms"]) == 1
    assert d["alarms"][0]["mode"] == "AboveValue"
    assert d["alarms"][0]["name"] == "Hi"
    assert d["historyEnabled"] is True
    assert d["historyProvider"] == "default"
    assert d["historicalDeadband"] == 0.1


def test_multiple_alarms_accumulate():
    a1 = Alarm(name="Hi", mode=TagAlarmMode.ABOVE_SETPOINT, setpointA=90.0)
    a2 = Alarm(name="Lo", mode=TagAlarmMode.BELOW_SETPOINT, setpointA=10.0)
    t = (
        TagBuilder()
        .name("Lvl")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .alarm(a1)
        .alarm(a2)
        .build()
    )
    names = [a["name"] for a in t.emit()["alarms"]]
    assert names == ["Hi", "Lo"]


def test_history_full_options():
    t = (
        TagBuilder()
        .name("H")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .history(
            provider="default",
            deadband=0.5,
            sample_rate=1.0,
            sample_rate_units="SEC",
            max_age=30,
            max_age_units="DAY",
        )
        .build()
    )
    d = t.emit()
    assert d["historyEnabled"] is True
    assert d["historyProvider"] == "default"
    assert d["historicalDeadband"] == 0.5
    assert d["historySampleRate"] == 1.0
    assert d["historySampleRateUnits"] == "SEC"
    assert d["historyMaxAge"] == 30
    assert d["historyMaxAgeUnits"] == "DAY"


def test_history_deadband_zero_omitted():
    """deadband=0.0 is the sentinel "not set" → don't emit historicalDeadband."""
    t = (
        TagBuilder()
        .name("H")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .history(provider="default")
        .build()
    )
    d = t.emit()
    assert d["historyEnabled"] is True
    assert d["historyProvider"] == "default"
    assert "historicalDeadband" not in d


# ---------- Expression / Query / Reference ----------


def test_expression_sets_source_and_expression():
    t = (
        TagBuilder()
        .name("E")
        .datatype(TagDataType.INTEGER)
        .expression("value + 1")
        .build()
    )
    d = t.emit()
    assert d["valueSource"] == "expr"
    assert d["expression"] == "value + 1"


def test_query_sets_source_query_and_optional_datasource():
    t = (
        TagBuilder()
        .name("Q")
        .datatype(TagDataType.INTEGER)
        .query("SELECT 1", datasource="MyDS")
        .build()
    )
    d = t.emit()
    assert d["valueSource"] == "db"
    assert d["query"] == "SELECT 1"
    assert d["datasource"] == "MyDS"


def test_query_without_datasource_omits_datasource():
    t = (
        TagBuilder()
        .name("Q")
        .datatype(TagDataType.INTEGER)
        .query("SELECT 1")
        .build()
    )
    d = t.emit()
    assert d["valueSource"] == "db"
    assert d["query"] == "SELECT 1"
    assert "datasource" not in d


def test_reference_sets_source_and_path():
    t = (
        TagBuilder()
        .name("R")
        .datatype(TagDataType.DOUBLE)
        .reference("[default]Folder/SourceTag")
        .build()
    )
    d = t.emit()
    assert d["valueSource"] == "reference"
    assert d["sourceTagPath"] == "[default]Folder/SourceTag"


# ---------- Tag-type / group / enabled ----------


def test_tag_group_and_enabled_propagate():
    t = (
        TagBuilder()
        .name("G")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .tag_group("Default")
        .enabled(False)
        .build()
    )
    d = t.emit()
    assert d["tagGroup"] == "Default"
    assert d["enabled"] is False


def test_explicit_tag_type_wins_over_default():
    t = (
        TagBuilder()
        .name("U")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .tag_type(TagType.UDT_INSTANCE)
        .build()
    )
    assert t.emit()["tagType"] == "UdtInstance"


def test_default_tag_type_is_atomic():
    t = (
        TagBuilder()
        .name("A")
        .datatype(TagDataType.DOUBLE)
        .opc("ns=1;s=test")
        .build()
    )
    assert t.emit()["tagType"] == "AtomicTag"


# ---------- Validation gates ----------


def test_missing_name_raises_validation_error():
    with pytest.raises(pydantic.ValidationError):
        TagBuilder().datatype(TagDataType.DOUBLE).memory().build()


def test_missing_datatype_raises_validation_error():
    with pytest.raises(pydantic.ValidationError):
        TagBuilder().name("X").memory().build()


def test_missing_value_source_raises_validation_error():
    with pytest.raises(pydantic.ValidationError):
        TagBuilder().name("X").datatype(TagDataType.DOUBLE).build()


# ---------- Builder-instance isolation ----------


def test_separate_builders_do_not_share_state():
    b1 = TagBuilder().name("A").datatype(TagDataType.DOUBLE).opc("ns=1;s=a")
    b2 = TagBuilder().name("B").datatype(TagDataType.FLOAT).memory()
    t1 = b1.build()
    t2 = b2.build()
    assert t1.emit()["name"] == "A"
    assert t1.emit()["valueSource"] == "opc"
    assert t2.emit()["name"] == "B"
    assert t2.emit()["valueSource"] == "memory"
    assert "opcItemPath" not in t2.emit()
