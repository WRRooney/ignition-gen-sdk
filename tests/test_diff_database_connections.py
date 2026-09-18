"""``ign diff database-connections`` tests.

Verifies the resource-type-agnostic ``cmd_diff.py`` discovers and operates
on ``database-connections`` manifest entries with no scaffolding change
beyond the help-text update.

Behavior (exit codes):

- sha256 match → exit 0; stdout contains "No diff".
- sha256 mismatch (unified diff mode) → exit 1; stdout contains +/- lines.
- sha256 mismatch (--json mode) → exit 1; stdout JSON has "changed" entry
  for the mutated key.
- No manifest entry for resource-id → exit 2; stderr "No manifest entry
  for database-connections/<name>".
- ``ign diff --help`` lists "database-connections" alongside the other
  resource types (verifies the help-text update).

Each test monkeypatches ``ignition_gen_sdk.manifest.manifest._MANIFEST_ROOT``
to a tmp dir and writes the manifest file directly (NOT via the CLI) so
this test file is independent of test_manifest_database_connections.py.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


# Canonical SQLite payload — same shape as fixtures/database-connections/Demo_DB.json.
_DEMO_DB_CFG: dict = {
    "connectURL": "jdbc:sqlite:${data}/Demo_DB.db",
    "connectionProps": "",
    "connectionResetParams": "",
    "defaultTransactionLevel": "DEFAULT",
    "driver": "SQLite",
    "evictionRate": -1,
    "evictionTests": 3,
    "evictionTime": 1800000,
    "failoverMode": "STANDARD",
    "failoverProfile": "",
    "includeSchemaInTableName": False,
    "poolInitSize": 0,
    "poolMaxActive": 8,
    "poolMaxIdle": 8,
    "poolMaxWait": 5000,
    "poolMinIdle": 0,
    "slowQueryLogThreshold": 60000,
    "testOnBorrow": True,
    "testOnReturn": False,
    "testWhileIdle": False,
    "translator": "SQLITE",
    "username": "",
    "validationQuery": "SELECT 1",
    "validationSleepTime": 10000,
}


def _redirect_manifest(tmp_dir: str | Path):
    target = Path(tmp_dir) / ".manifest"
    p = patch(
        "ignition_gen_sdk.manifest.manifest._MANIFEST_ROOT",
        target,
    )
    p.start()
    return p.stop, target


def _seed_manifest(manifest_dir: Path, resource_id: str, payload: dict) -> Path:
    """Write the database-connections.json directly with a single seeded entry."""
    from ignition_gen_sdk.manifest.manifest import _sha256
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "database-connections.json"
    entry = {
        resource_id: {
            "payload": payload,
            "sha256": _sha256(payload),
            "timestamp": "2026-05-17T12:00:00+00:00",
            "backend": "api",
        },
    }
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return path


def _write_current(tmp_dir: str | Path, payload: dict,
                   name: str = "current.json") -> str:
    path = Path(tmp_dir) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# sha256 match → exit 0
# ---------------------------------------------------------------------------

class TestDiffSha256Match(unittest.TestCase):
    def test_diff_sha256_match_exits_0(self) -> None:
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _seed_manifest(manifest_dir, "Demo_DB", _DEMO_DB_CFG)
            current = _write_current(td, _DEMO_DB_CFG)
            try:
                result = _runner().invoke(
                    app,
                    [
                        "diff", "database-connections", "Demo_DB",
                        "--current-file", current,
                    ],
                )
            finally:
                stop_manifest()
            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))
            self.assertIn("No diff", result.stdout)


# ---------------------------------------------------------------------------
# sha256 mismatch → unified diff, exit 1
# ---------------------------------------------------------------------------

class TestDiffDriftUnified(unittest.TestCase):
    def test_diff_drift_exits_1_with_unified_diff(self) -> None:
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _seed_manifest(manifest_dir, "Demo_DB", _DEMO_DB_CFG)
            mutated = dict(_DEMO_DB_CFG)
            mutated["poolMaxActive"] = 16
            current = _write_current(td, mutated)
            try:
                result = _runner().invoke(
                    app,
                    [
                        "diff", "database-connections", "Demo_DB",
                        "--current-file", current,
                        "--no-color",  # plain text for stable assertion
                    ],
                )
            finally:
                stop_manifest()
            self.assertEqual(result.exit_code, 1,
                             msg=(result.stdout or "") + (result.stderr or ""))
            combined = (result.stdout or "") + (result.stderr or "")
            # New value present as a +/added line; old value as -/removed.
            self.assertIn('"poolMaxActive": 16', combined)
            self.assertIn('"poolMaxActive": 8', combined)
            # difflib formatting markers
            self.assertTrue(
                any(line.startswith("+") for line in combined.splitlines()),
                msg=f"expected at least one '+' line in: {combined!r}",
            )
            self.assertTrue(
                any(line.startswith("-") for line in combined.splitlines()),
                msg=f"expected at least one '-' line in: {combined!r}",
            )


# ---------------------------------------------------------------------------
# sha256 mismatch → --json mode, exit 1
# ---------------------------------------------------------------------------

class TestDiffDriftJson(unittest.TestCase):
    def test_diff_drift_json_mode(self) -> None:
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _seed_manifest(manifest_dir, "Demo_DB", _DEMO_DB_CFG)
            mutated = dict(_DEMO_DB_CFG)
            mutated["poolMaxActive"] = 16
            current = _write_current(td, mutated)
            try:
                result = _runner().invoke(
                    app,
                    [
                        "diff", "database-connections", "Demo_DB",
                        "--current-file", current,
                        "--json",
                    ],
                )
            finally:
                stop_manifest()
            self.assertEqual(result.exit_code, 1,
                             msg=(result.stdout or "") + (result.stderr or ""))
            payload = json.loads(result.stdout)
            self.assertIn("changed", payload)
            self.assertIn("poolMaxActive", payload["changed"])
            # _diff_to_json shape: [old, new]
            self.assertEqual(payload["changed"]["poolMaxActive"], [8, 16])
            # No spurious added/removed at the top-level keys (same keyset).
            self.assertEqual(payload.get("added", {}), {})
            self.assertEqual(payload.get("removed", {}), {})


# ---------------------------------------------------------------------------
# No manifest entry → exit 2
# ---------------------------------------------------------------------------

class TestDiffNoManifestEntry(unittest.TestCase):
    def test_diff_missing_manifest_exits_2(self) -> None:
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, _manifest_dir = _redirect_manifest(td)
            # do NOT seed any manifest
            current = _write_current(td, _DEMO_DB_CFG)
            try:
                result = _runner().invoke(
                    app,
                    [
                        "diff", "database-connections", "Demo_DB",
                        "--current-file", current,
                    ],
                )
            finally:
                stop_manifest()
            self.assertEqual(result.exit_code, 2,
                             msg=(result.stdout or "") + (result.stderr or ""))
            self.assertIn(
                "No manifest entry for database-connections/Demo_DB",
                result.stderr,
            )


# ---------------------------------------------------------------------------
# Help-text discoverability
# ---------------------------------------------------------------------------

class TestDiffHelpListsDatabaseConnections(unittest.TestCase):
    def test_diff_help_lists_database_connections(self) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["diff", "--help"])
        self.assertEqual(result.exit_code, 0,
                         msg=(result.stdout or "") + (result.stderr or ""))
        self.assertIn("database-connections", result.output)


if __name__ == "__main__":
    unittest.main()
