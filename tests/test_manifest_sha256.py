"""Tests for manifest._sha256 canonical form + record/read round-trip.

Locks the idempotency invariants verified live: the stored sha256 is
canonical (sort_keys + separators=(',',':')), so it is deterministic,
key-order-independent, and identical whether the payload is built fresh or
reloaded. This is what makes `ign diff` reliable.
"""
from __future__ import annotations

from ignition_gen_sdk.manifest import manifest as m

_A = {"name": "T01", "value": 3.2, "nested": {"x": 1, "y": 2}}
_A_REORDERED = {"nested": {"y": 2, "x": 1}, "value": 3.2, "name": "T01"}


def test_sha256_idempotent() -> None:
    assert m._sha256(_A) == m._sha256(_A)


def test_sha256_key_order_independent() -> None:
    # canonical form sorts keys, so logically-equal payloads hash identically
    assert m._sha256(_A) == m._sha256(_A_REORDERED)


def test_sha256_is_64_hex() -> None:
    h = m._sha256(_A)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_accepts_list() -> None:
    # Disk backend stores bare lists to match on-disk tags.json shape
    assert isinstance(m._sha256([1, 2, {"k": "v"}]), str)


def test_sha256_distinct_payloads_differ() -> None:
    assert m._sha256(_A) != m._sha256({"name": "T02"})


def test_record_read_roundtrip(tmp_path, monkeypatch) -> None:
    # redirect the module-level manifest root at a tmp dir so the real
    # .manifest/ is never touched
    monkeypatch.setattr(m, "_MANIFEST_ROOT", tmp_path / ".manifest")
    m.record("tags", "default/Tanks/T01", _A, "disk")
    entry = m.read("tags", "default/Tanks/T01")
    assert entry is not None
    assert entry["sha256"] == m._sha256(_A)
    assert entry["backend"] == "disk"
    assert entry["payload"] == _A
    # reordered-but-equal payload yields the SAME stored sha256
    m.record("tags", "default/Tanks/T01", _A_REORDERED, "disk")
    assert m.read("tags", "default/Tanks/T01")["sha256"] == m._sha256(_A)
