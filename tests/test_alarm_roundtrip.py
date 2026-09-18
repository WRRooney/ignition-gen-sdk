"""Alarm + tag/alarm round-trip vs samplequickstart_tags.json.

Verifies the Alarm model emits a JSON shape that matches the sample alarm
fields used in `samplequickstart_tags.json` (lines 57-75 of that file):
``displayPath``, ``mode``, ``name``, ``notes``, ``priority``, ``setpointA``.

Also verifies the 8.3 boolean-tag alarm modes ``WhenTrue`` / ``WhenFalse``
are reachable from the Alarm model and emit their literal string values,
and that a Tag with an embedded Alarm round-trips correctly.
"""
from __future__ import annotations

from ignition_gen_sdk.models.tags.alarm import Alarm
from ignition_gen_sdk.models.tags.enums.tag_alarm_mode import TagAlarmMode
from ignition_gen_sdk.models.tags.enums.tag_alarm_priority import TagAlarmPriority
from ignition_gen_sdk.models.tags.tag import Tag


def test_alarm_emits_sample_shape_fields():
    """The 6 fields present in the sample alarm must round-trip exactly."""
    a = Alarm(
        name="Hi",
        mode=TagAlarmMode.ABOVE_SETPOINT,
        priority=TagAlarmPriority.CRITICAL,
        setpointA=90.0,
        displayPath="Level Hi Alarm",
        notes="Level is too high",
    )
    d = a.emit()
    assert d["name"] == "Hi"
    assert d["mode"] == "AboveValue"
    assert d["priority"] == "Critical"
    assert d["setpointA"] == 90.0
    assert d["displayPath"] == "Level Hi Alarm"
    assert d["notes"] == "Level is too high"


def test_alarm_when_true_mode_value():
    assert TagAlarmMode.WHEN_TRUE.value == "WhenTrue"
    a = Alarm(name="On", mode=TagAlarmMode.WHEN_TRUE)
    assert a.emit()["mode"] == "WhenTrue"


def test_alarm_when_false_mode_value():
    assert TagAlarmMode.WHEN_FALSE.value == "WhenFalse"
    a = Alarm(name="Off", mode=TagAlarmMode.WHEN_FALSE)
    assert a.emit()["mode"] == "WhenFalse"


def test_tag_with_embedded_alarm_round_trip():
    """Reproduces the WriteableInteger1 shape from samplequickstart_tags.json."""
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
    )
    td = t.emit()
    assert "alarms" in td
    assert len(td["alarms"]) == 1
    alarm_d = td["alarms"][0]
    assert alarm_d["mode"] == "AboveValue"
    assert alarm_d["priority"] == "Critical"
    assert alarm_d["name"] == "Hi"
    assert alarm_d["setpointA"] == 90.0
    assert alarm_d["displayPath"] == "Level Hi Alarm"
    assert alarm_d["notes"] == "Level is too high"
    # Top-level OPC fields preserved
    assert td["opcServer"] == "Ignition OPC UA Server"
    assert td["dataType"] == "Int4"
    assert td["valueSource"] == "opc"


def test_alarm_minimal_construct_succeeds():
    """Alarm with only name + mode must construct (defaults fill the rest)."""
    a = Alarm(name="X", mode=TagAlarmMode.WHEN_TRUE)
    d = a.emit()
    assert d["name"] == "X"
    assert d["mode"] == "WhenTrue"
    # Defaults that are non-None will emit; that is acceptable Ignition behavior
    assert d["enabled"] is True
    assert d["priority"] == "Low"


def test_alarm_priority_enum_maps_to_strings():
    """All 5 priorities must round-trip as Ignition-recognized strings."""
    for prio, expected in [
        (TagAlarmPriority.DIAGNOSTIC, "Diagnostic"),
        (TagAlarmPriority.LOW, "Low"),
        (TagAlarmPriority.MEDIUM, "Medium"),
        (TagAlarmPriority.HIGH, "High"),
        (TagAlarmPriority.CRITICAL, "Critical"),
    ]:
        a = Alarm(name="A", mode=TagAlarmMode.WHEN_TRUE, priority=prio)
        assert a.emit()["priority"] == expected


def test_alarm_import_path_in_tag_module_is_local():
    """Regression: tag.py must import Alarm via the local relative path,
    not a stale copy of the class.
    """
    import ignition_gen_sdk.models.tags.tag as tag_mod

    assert tag_mod.Alarm is Alarm, "Tag module's Alarm symbol must be the same class"
