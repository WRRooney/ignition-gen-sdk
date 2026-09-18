"""manifest persistence for ``ign db-conn``.

Verifies the three call sites added to ``cmd_db_conn.py`` :

- ``create_cmd`` writes a manifest entry with the inner ConnectionConfig dict.
- ``update_cmd`` overwrites the entry with the new payload + fresh timestamp.
- ``delete_cmd`` overwrites the entry with ``payload={}`` (deletion tombstone).
- ``--dry-run`` skips the manifest entirely (returns BEFORE the API call).
- ``--no-scan`` still writes the manifest (manifest precedes scan in source order).
- A ``ScanWarning`` from the scan step does NOT invalidate the manifest
  (ordering invariant — manifest runs first).
- The on-disk manifest filename is plural ``database-connections.json``
  (NOT singular — per the established codebase convention).

Each test monkeypatches ``ignition_gen_sdk.manifest.manifest._MANIFEST_ROOT``
to a ``tmp_path / ".manifest"`` so the real .manifest/ directory is never
touched and tests are fully isolated from each other.

Mirrors the patching pattern from tests/test_cli_db_conn.py: patch
ApiBackend / IgnitionAPIClient / ScanClient at the cmd module surface so
the live gateway is not contacted.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_cli_db_conn.py)
# ---------------------------------------------------------------------------

def _runner():
    from typer.testing import CliRunner
    return CliRunner()


# Canonical SQLite fixture — matches fixtures/database-connections/Demo_DB.json
# in shape (no password key). The same shape is what the gateway POST body
# carries and what the manifest stores in `payload`.
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

_DRIVERS_OK = [{"name": "SQLite", "enabled": True}, {"name": "MySQL", "enabled": True}]


def _write_cfg(tmp_dir: str | Path, payload: dict, name: str = "cfg.json") -> str:
    path = Path(tmp_dir) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _patch_cli(driver_list=None):
    """Patch ApiBackend / IgnitionAPIClient / ScanClient at the cmd module surface.

    Returns (api_cls, api_inst, scan_cls, scan_inst, stop_all).
    """
    api_cls_p = patch("ignition_gen_sdk.cli.cmd_db_conn.ApiBackend")
    api_client_p = patch("ignition_gen_sdk.cli.cmd_db_conn.IgnitionAPIClient")
    scan_cls_p = patch("ignition_gen_sdk.cli.cmd_db_conn.ScanClient")

    api_cls = api_cls_p.start()
    api_client_p.start()
    scan_cls = scan_cls_p.start()

    api_inst = MagicMock()
    api_inst.list_drivers.return_value = (
        driver_list if driver_list is not None else _DRIVERS_OK
    )
    api_cls.return_value = api_inst

    scan_inst = MagicMock()
    scan_cls.return_value.__enter__.return_value = scan_inst
    scan_cls.return_value.__exit__.return_value = False

    def stop_all():
        api_cls_p.stop()
        api_client_p.stop()
        scan_cls_p.stop()

    return api_cls, api_inst, scan_cls, scan_inst, stop_all


def _redirect_manifest(tmp_dir: str | Path):
    """Replace _MANIFEST_ROOT so tests do not write to the real .manifest/.

    Returns a stop() callable; tests must call it in a finally block.
    """
    from pathlib import Path as _P
    target = _P(tmp_dir) / ".manifest"
    p = patch(
        "ignition_gen_sdk.manifest.manifest._MANIFEST_ROOT",
        target,
    )
    p.start()
    return p.stop, target


def _seed_manifest(manifest_dir: Path, resource_id: str, payload: dict,
                   timestamp: str = "2020-01-01T00:00:00+00:00") -> Path:
    """Write a pre-existing database-connections.json with one entry."""
    from ignition_gen_sdk.manifest.manifest import _sha256
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "database-connections.json"
    entry = {
        resource_id: {
            "payload": payload,
            "sha256": _sha256(payload),
            "timestamp": timestamp,
            "backend": "api",
        },
    }
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return path


# Common stdin patch — db-conn create/update _resolve_password reaches
# sys.stdin.isatty() when no --password-stdin and no password key. Tests
# below patch this to False so the branch (5) pass-through path fires.
def _patch_stdin_no_tty():
    p = patch("ignition_gen_sdk.cli.cmd_db_conn.sys.stdin")
    m = p.start()
    m.isatty.return_value = False
    return p.stop


# ---------------------------------------------------------------------------
# Manifest write tests
# ---------------------------------------------------------------------------

class TestManifestWriteOnCreate(unittest.TestCase):
    def test_create_writes_manifest_entry(self) -> None:
        """create_cmd writes payload, sha256, timestamp, backend='api'."""
        from ignition_gen_sdk.cli import app
        from ignition_gen_sdk.manifest.manifest import _sha256
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _DEMO_DB_CFG)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            stop_manifest, manifest_dir = _redirect_manifest(td)
            stop_stdin = _patch_stdin_no_tty()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))

            manifest_path = manifest_dir / "database-connections.json"
            self.assertTrue(manifest_path.exists(),
                            msg=f"manifest file missing at {manifest_path}")

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("Demo_DB", data)
            entry = data["Demo_DB"]
            # payload is the inner config_dict, not the api envelope
            self.assertEqual(entry["payload"], _DEMO_DB_CFG)
            self.assertEqual(entry["sha256"], _sha256(_DEMO_DB_CFG))
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertEqual(entry["backend"], "api")
            # ISO 8601 timestamp shape
            self.assertRegex(entry["timestamp"],
                             r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class TestManifestOverwriteOnUpdate(unittest.TestCase):
    def test_update_overwrites_manifest_entry(self) -> None:
        """update_cmd replaces the prior payload + sha256 + timestamp."""
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, manifest_dir = _redirect_manifest(td)
            # Pre-seed with old payload (poolMaxActive=8)
            old_payload = dict(_DEMO_DB_CFG)
            old_payload["poolMaxActive"] = 8
            _seed_manifest(manifest_dir, "Demo_DB", old_payload,
                           timestamp="2020-01-01T00:00:00+00:00")

            new_payload = dict(_DEMO_DB_CFG)
            new_payload["poolMaxActive"] = 16
            cfg_path = _write_cfg(td, new_payload)

            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                # update_cmd two-call: get then update
                api_inst.get_connection.return_value = {
                    "name": "Demo_DB",
                    "signature": "sig-old",
                    "config": old_payload,
                }
                api_inst.update_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "update",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))

            data = json.loads(
                (manifest_dir / "database-connections.json").read_text(encoding="utf-8")
            )
            entry = data["Demo_DB"]
            self.assertEqual(entry["payload"]["poolMaxActive"], 16)
            # timestamp must be newer than the seed
            self.assertNotEqual(entry["timestamp"], "2020-01-01T00:00:00+00:00")
            self.assertGreater(entry["timestamp"], "2020-01-01T00:00:00+00:00")


class TestManifestTombstoneOnDelete(unittest.TestCase):
    def test_delete_tombstones_manifest_entry(self) -> None:
        """delete_cmd overwrites entry with payload={} (tombstone)."""
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _seed_manifest(manifest_dir, "Demo_DB", _DEMO_DB_CFG)

            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.get_connection.return_value = {
                    "name": "Demo_DB",
                    "signature": "sig-x",
                    "config": _DEMO_DB_CFG,
                }
                api_inst.delete_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "delete",
                        "--name", "Demo_DB",
                        "--yes",
                        "--no-scan",
                    ],
                )
            finally:
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))

            data = json.loads(
                (manifest_dir / "database-connections.json").read_text(encoding="utf-8")
            )
            self.assertIn("Demo_DB", data)
            entry = data["Demo_DB"]
            self.assertEqual(entry["payload"], {})
            self.assertEqual(entry["backend"], "api")


# ---------------------------------------------------------------------------
# Dry-run + ordering invariants
# ---------------------------------------------------------------------------

class TestManifestDryRunSkip(unittest.TestCase):
    def test_dry_run_does_not_touch_manifest(self) -> None:
        """--dry-run returns BEFORE the API call AND before manifest write."""
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _DEMO_DB_CFG)
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--dry-run",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))
            # Manifest file does NOT exist (no record() ever fired).
            self.assertFalse(
                (manifest_dir / "database-connections.json").exists(),
                msg="manifest must NOT be written during --dry-run",
            )
            api_inst.create_connection.assert_not_called()


class TestManifestNoScanStillWrites(unittest.TestCase):
    def test_create_no_scan_still_writes_manifest(self) -> None:
        """--no-scan suppresses the scan step but the manifest record still fires."""
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _DEMO_DB_CFG)
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _api_cls, api_inst, scan_cls, _scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))
            # Scan was suppressed
            scan_cls.assert_not_called()
            # Manifest WAS written
            mfile = manifest_dir / "database-connections.json"
            self.assertTrue(mfile.exists())
            data = json.loads(mfile.read_text(encoding="utf-8"))
            self.assertIn("Demo_DB", data)
            self.assertEqual(data["Demo_DB"]["payload"], _DEMO_DB_CFG)


class TestManifestSurvivesScanWarning(unittest.TestCase):
    def test_create_scan_warning_does_not_invalidate_manifest(self) -> None:
        """Manifest runs BEFORE scan. ScanWarning is a stderr WARNING, not a revert."""
        from ignition_gen_sdk.backends.scan_client import ScanWarning
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _DEMO_DB_CFG)
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _api_cls, api_inst, _scan_cls, scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                api_inst.create_connection.return_value = {"success": True}
                scan_inst.scan_config.side_effect = ScanWarning("simulated scan failure")
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        # default --scan path
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))
            self.assertIn("WARNING:", result.stderr)
            # Manifest still on disk despite scan failure.
            mfile = manifest_dir / "database-connections.json"
            self.assertTrue(mfile.exists(),
                            msg="manifest must survive a ScanWarning")
            data = json.loads(mfile.read_text(encoding="utf-8"))
            self.assertIn("Demo_DB", data)
            self.assertEqual(data["Demo_DB"]["payload"], _DEMO_DB_CFG)


# ---------------------------------------------------------------------------
# sha256 canonicalization + resource-type plural lock
# ---------------------------------------------------------------------------

class TestManifestSha256Canonical(unittest.TestCase):
    def test_manifest_sha256_is_canonical(self) -> None:
        """Stored sha256 must equal _sha256(payload) (canonical, sort_keys, no whitespace)."""
        from ignition_gen_sdk.cli import app
        from ignition_gen_sdk.manifest.manifest import _sha256
        # Specifically reorder keys in the source file to confirm sort_keys
        # canonicalization is what's hashed (NOT the input byte order).
        reordered = {k: _DEMO_DB_CFG[k] for k in sorted(_DEMO_DB_CFG.keys(), reverse=True)}
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, reordered)
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))

            data = json.loads(
                (manifest_dir / "database-connections.json").read_text(encoding="utf-8")
            )
            entry = data["Demo_DB"]
            stored_payload = entry["payload"]
            self.assertEqual(entry["sha256"], _sha256(stored_payload))
            # And — the canonical hash for reordered vs original input matches
            # because _sha256 sorts keys before hashing.
            self.assertEqual(_sha256(stored_payload), _sha256(_DEMO_DB_CFG))


class TestManifestResourceTypePlural(unittest.TestCase):
    def test_resource_type_string_is_plural(self) -> None:
        """Filename is database-connections.json (plural). Guards against drift.

        The codebase
        convention is plural (providers.json, views.json, tags.json). This test
        locks the plural form in.
        """
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _DEMO_DB_CFG)
            stop_manifest, manifest_dir = _redirect_manifest(td)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            stop_stdin = _patch_stdin_no_tty()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop_stdin()
                stop_manifest()
                stop()

            self.assertEqual(result.exit_code, 0,
                             msg=(result.stdout or "") + (result.stderr or ""))

            # PLURAL exists
            self.assertTrue(
                (manifest_dir / "database-connections.json").exists(),
                msg="plural filename database-connections.json must exist",
            )
            # SINGULAR does NOT exist
            self.assertFalse(
                (manifest_dir / "database-connection.json").exists(),
                msg="singular filename database-connection.json must NOT exist",
            )


if __name__ == "__main__":
    unittest.main()
