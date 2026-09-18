"""Tests for offline UDT-instance import-body validation."""
from __future__ import annotations

import json
from pathlib import Path

from ignition_gen_sdk.validation.instance_body import (
    collect_udt_typeids,
    validate_instance_body,
)

_PUMP = {"name": "P1", "tagType": "UdtInstance", "typeId": "Types/Pump"}


def _body(*instances):
    return {"tags": [{"name": "Sim", "tagType": "Folder", "tags": list(instances)}]}


def test_flags_missing_typeid():
    body = _body({"name": "NoType", "tagType": "UdtInstance"})
    count, used, issues = validate_instance_body(body, set())
    assert count == 1
    assert any("missing/blank typeId" in i and "NoType" in i for i in issues)


def test_flags_blank_typeid():
    body = _body({"name": "Blank", "tagType": "UdtInstance", "typeId": "   "})
    _, _, issues = validate_instance_body(body, set())
    assert any("missing/blank typeId" in i for i in issues)


def test_flags_unknown_typeid_when_defs_present():
    body = _body(
        _PUMP,
        {"name": "Typo", "tagType": "UdtInstance", "typeId": "Types/Pmup"},
    )
    valid = {"Types/Pump", "Types/Valve"}
    count, used, issues = validate_instance_body(body, valid)
    assert count == 2
    assert used == {"Types/Pump", "Types/Pmup"}
    assert any("Pmup" in i and "not found" in i for i in issues)
    # The valid Pump must NOT be flagged.
    assert not any("Types/Pump'" in i for i in issues)


def test_structural_only_when_no_typeids_known():
    # Empty valid set → unknown-typeId resolution is skipped (degraded mode);
    # only the missing-typeId structural check runs.
    body = _body(
        {"name": "Typo", "tagType": "UdtInstance", "typeId": "Types/Pmup"},
        {"name": "NoType", "tagType": "UdtInstance"},
    )
    _, _, issues = validate_instance_body(body, set())
    assert any("NoType" in i for i in issues)
    assert not any("not found" in i for i in issues)  # not resolved


def test_bare_list_body_supported():
    count, _, _ = validate_instance_body([_PUMP, _PUMP], {"Types/Pump"})
    assert count == 2


def test_collect_udt_typeids_from_disk(tmp_path: Path):
    base = (
        tmp_path / "config" / "resources" / "core" / "ignition"
        / "tag-type-definition" / "default" / "Types"
    )
    base.mkdir(parents=True)
    (base / "udts.json").write_text(
        json.dumps([
            {"name": "Pump", "tagType": "UdtType"},
            {"name": "Valve", "tagType": "UdtType"},
        ])
    )
    got = collect_udt_typeids(tmp_path, "default")
    assert got == {"Types/Pump", "Types/Valve"}


def test_collect_udt_typeids_absent_tree_returns_empty(tmp_path: Path):
    assert collect_udt_typeids(tmp_path, "default") == set()


def test_cli_dry_run_flags_typo(tmp_path: Path):
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app

    f = tmp_path / "inst.json"
    f.write_text(json.dumps(_body(
        {"name": "Typo", "tagType": "UdtInstance", "typeId": "Types/Pmup"},
    )))
    r = CliRunner().invoke(
        app, ["tag", "import", "--provider", "default", "--file", str(f), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "=== UDT instances ===" in r.output
    # The typo is reported regardless of whether the type defs resolve.
    assert "Pmup" in r.output
