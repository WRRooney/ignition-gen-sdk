"""Regression lock: the Alarm model must cover every alarm-config KEY,
``mode`` value, and ``priority`` value that the on-disk IA / framework corpus
actually uses.

The Alarm model inherits ``extra="forbid"``; ``mode``/``priority`` are enums.
So a real alarm property the model omits — or an enum value it lacks — would
FALSE-REJECT a legitimate alarm at author time. This scans the gateway's
tag-type-definition + tag-definition resources (IndustryPack UDTs, the Sim
alarm tags, etc.) and asserts full coverage. Guards against a future model edit
narrowing the field set or an enum. Skips if no alarm configs are present.

Audited live across 42 alarm configs: keys all covered; modes used =
{AboveValue, BelowValue, WhenTrue, OutsideValues}; priorities used =
{High, Low, Medium, Critical, Diagnostic}. All in the model/enums.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ignition_gen_sdk.models.tags.alarm import Alarm, TagAlarmMode, TagAlarmPriority

# Corpus tests scan a real gateway data dir READ-ONLY; point IGNITION_CORPUS_DIR at one.
_DATA = Path(os.environ.get("IGNITION_CORPUS_DIR") or "/nonexistent")


def _alarm_corpus_roots() -> list[Path]:
    candidates = [
        _DATA / "config" / "resources" / "core" / "ignition" / "tag-type-definition",
        _DATA / "config" / "resources" / "core" / "ignition" / "tag-definition",
    ]
    return [c for c in candidates if c.exists()]


def _model_keys() -> set[str]:
    keys = set(Alarm.model_fields.keys())
    for f in Alarm.model_fields.values():
        if f.alias:
            keys.add(f.alias)
    return keys


def _collect():
    """Return (alarm_count, bad_keys, bad_modes, bad_priorities)."""
    fields = _model_keys()
    mode_vals = {v.value for v in TagAlarmMode}
    pri_vals = {v.value for v in TagAlarmPriority}
    bad_keys: set[str] = set()
    bad_modes: set[str] = set()
    bad_pris: set[str] = set()
    count = 0

    def walk(o):
        nonlocal count
        if isinstance(o, dict):
            al = o.get("alarms")
            if isinstance(al, list):
                for a in al:
                    if isinstance(a, dict):
                        count += 1
                        for k in a:
                            if k not in fields:
                                bad_keys.add(k)
                        if isinstance(a.get("mode"), str) and a["mode"] not in mode_vals:
                            bad_modes.add(a["mode"])
                        if isinstance(a.get("priority"), str) and a["priority"] not in pri_vals:
                            bad_pris.add(a["priority"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for root in _alarm_corpus_roots():
        for jf in root.rglob("*.json"):
            try:
                walk(json.loads(jf.read_text(encoding="utf-8")))
            except Exception:
                continue
    return count, bad_keys, bad_modes, bad_pris


def test_alarm_model_covers_ia_corpus() -> None:
    if not _alarm_corpus_roots():
        pytest.skip("tag resources not present")
    count, bad_keys, bad_modes, bad_pris = _collect()
    if count == 0:
        pytest.skip("no alarm configs in corpus")
    assert not bad_keys, f"alarm keys used in corpus but NOT modeled: {sorted(bad_keys)}"
    assert not bad_modes, f"alarm 'mode' values not in TagAlarmMode: {sorted(bad_modes)}"
    assert not bad_pris, f"alarm 'priority' values not in TagAlarmPriority: {sorted(bad_pris)}"
