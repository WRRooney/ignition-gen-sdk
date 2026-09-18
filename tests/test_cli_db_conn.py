"""``ign db-conn`` CLI tests.

Mirrors tests/test_cli_driver.py and tests/test_cli_view_mvp.py patterns.

Patch ``ignition_gen_sdk.cli.cmd_db_conn.ApiBackend`` (the class as
imported into the cmd module) so the live gateway is not contacted.
Also patch ``IgnitionAPIClient`` (instantiated inside _get_api before
ApiBackend) and ``ScanClient`` (instantiated in _scan_after_mutation).

Behavior contracts:

- 9 verbs wired and discoverable.
- ``db-conn list / names / get / describe`` print JSON; exit 0.
- ``db-conn get`` with a 404 yields ``Error: connection '<name>' not found.``.
- ``db-conn create``:
    * --dry-run prints {name, config} JSON; no HTTP, no scan.
    * --password-stdin with non-empty pipe → password injected into config_dict.
    * --password-stdin with empty pipe → no injection (legitimate SQLite case).
    * No flag + isatty()=True → typer.prompt called; result injected if non-empty.
    * No flag + isatty()=False + no password key → pass through (no prompt, no error).
    * JWE-shaped password in config-file → JWE-refusal ValueError → render_error → exit 1.
    * Outer backupConfig in config-file → backupConfig Hint → exit 1.
    * Inner-nested backupConfig (slipped past the pop) → generic extra="forbid" reject.
    * Unknown driver → _validate_driver raises PayloadError → exit 1; create_connection NOT called.
    * --scan default → ScanClient.scan_config called once.
    * --no-scan → ScanClient never instantiated.
    * ScanWarning → stderr ``WARNING:`` line; exit 0.
- ``db-conn update``:
    * Two-call: api.get_connection then api.update_connection(name, sig, config=...).
    * --dry-run skips both calls.
    * 404 → "connection '<name>' not found.".
- ``db-conn delete``:
    * --yes → no prompt; two-call delete.
    * No --yes + input='y\\n' → confirmed; delete fires.
    * No --yes + input='n\\n' → aborted; api.delete_connection NOT called.
- ``db-conn delete-bulk`` reads JSON list and forwards.
- ``db-conn rename`` calls api.rename_connection(name, new_name).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _runner():
    from typer.testing import CliRunner
    # Typer 0.25.x / Click 8.2+ — CliRunner separates stdout/stderr automatically.
    return CliRunner()


# Minimal SQLite-flavored config dict (no password — matches the live smoke).
_SQLITE_CFG: dict = {
    "driver": "SQLite",
    "translator": "SQLITE",
    "connectURL": "jdbc:sqlite:${data}/Demo_DB.db",
    "username": "",
    "connectionProps": "",
    "connectionResetParams": "",
    "defaultTransactionLevel": "DEFAULT",
    "poolInitSize": 0,
    "poolMaxActive": 8,
    "poolMaxIdle": 8,
    "poolMinIdle": 0,
    "poolMaxWait": 5000,
    "validationQuery": "SELECT 1",
    "testOnBorrow": True,
    "testOnReturn": False,
    "testWhileIdle": False,
    "evictionRate": -1,
    "evictionTests": 3,
    "evictionTime": 1800000,
    "failoverProfile": "",
    "failoverMode": "STANDARD",
    "slowQueryLogThreshold": 60000,
    "validationSleepTime": 10000,
    "includeSchemaInTableName": False,
}

# MySQL-flavored config dict (no password key) — used for tty-prompt path.
_MYSQL_CFG_NO_PW: dict = {
    **_SQLITE_CFG,
    "driver": "MySQL",
    "translator": "MYSQL",
    "connectURL": "jdbc:mysql://localhost:3306/test",
    "username": "root",
}

# Default driver list used by _validate_driver — includes SQLite + MySQL.
_DRIVERS_OK = [
    {"name": "SQLite", "enabled": True},
    {"name": "MySQL", "enabled": True},
]


def _write_cfg(tmp_dir: str, payload: dict, name: str = "cfg.json") -> str:
    path = Path(tmp_dir) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _patch_cli(driver_list=None):
    """Return a context-manager dict of common patches used in most tests.

    Patches ApiBackend, IgnitionAPIClient, and ScanClient on the cmd module.
    Returns (mock_api_class, mock_api_instance, mock_scan_class, mock_scan_instance).
    """
    api_cls_p = patch("ignition_gen_sdk.cli.cmd_db_conn.ApiBackend")
    api_client_p = patch("ignition_gen_sdk.cli.cmd_db_conn.IgnitionAPIClient")
    scan_cls_p = patch("ignition_gen_sdk.cli.cmd_db_conn.ScanClient")

    api_cls = api_cls_p.start()
    api_client_p.start()
    scan_cls = scan_cls_p.start()

    api_inst = MagicMock()
    api_inst.list_drivers.return_value = driver_list if driver_list is not None else _DRIVERS_OK
    api_cls.return_value = api_inst

    scan_inst = MagicMock()
    # Make the ScanClient usable as a context manager.
    scan_cls.return_value.__enter__.return_value = scan_inst
    scan_cls.return_value.__exit__.return_value = False

    def stop_all():
        api_cls_p.stop()
        api_client_p.stop()
        scan_cls_p.stop()

    return api_cls, api_inst, scan_cls, scan_inst, stop_all


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

class TestCliWiring(unittest.TestCase):
    def test_top_level_help_lists_db_conn(self) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("db-conn", result.output)

    def test_db_conn_help_lists_all_9_verbs(self) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["db-conn", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        for verb in ("list", "names", "get", "create", "update",
                     "delete", "delete-bulk", "rename", "describe"):
            self.assertIn(verb, result.output, msg=f"verb {verb} missing")


# ---------------------------------------------------------------------------
# Read-only verbs
# ---------------------------------------------------------------------------

class TestReadOnlyVerbs(unittest.TestCase):
    def test_list_prints_json(self) -> None:
        from ignition_gen_sdk.cli import app
        fake = [{"name": "Demo_DB", "enabled": True}, {"name": "Sensors_DB", "enabled": True}]
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.list_connections.return_value = fake
            result = _runner().invoke(app, ["db-conn", "list"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertEqual(json.loads(result.stdout), fake)
        api_inst.list_connections.assert_called_once()

    def test_names_prints_json_list(self) -> None:
        from ignition_gen_sdk.cli import app
        fake = ["Demo_DB", "Sensors_DB"]
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.get_connection_names.return_value = fake
            result = _runner().invoke(app, ["db-conn", "names"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertEqual(json.loads(result.stdout), fake)

    def test_get_prints_json(self) -> None:
        from ignition_gen_sdk.cli import app
        fake = {"name": "Demo_DB", "signature": "sig123", "config": _SQLITE_CFG}
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.get_connection.return_value = fake
            result = _runner().invoke(app, ["db-conn", "get", "Demo_DB"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertEqual(json.loads(result.stdout), fake)
        api_inst.get_connection.assert_called_once_with("Demo_DB")

    def test_get_not_found_message(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.cli import app
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.get_connection.side_effect = PayloadError(
                "404 Not Found"
            )
            result = _runner().invoke(app, ["db-conn", "get", "Foo"])
        finally:
            stop()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("connection 'Foo' not found.", result.stderr)
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)

    def test_describe_prints_json(self) -> None:
        from ignition_gen_sdk.cli import app
        fake = {"type": "ignition.database-connection", "extensionPoints": []}
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.describe_connection_type.return_value = fake
            result = _runner().invoke(app, ["db-conn", "describe"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertEqual(json.loads(result.stdout), fake)


# ---------------------------------------------------------------------------
# Create verb
# ---------------------------------------------------------------------------

class TestCreateVerb(unittest.TestCase):
    def test_create_dry_run_no_http(self) -> None:
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, _SQLITE_CFG)
            _api_cls, api_inst, scan_cls, _scan_inst, stop = _patch_cli()
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
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "Demo_DB")
        self.assertEqual(payload["config"]["driver"], "SQLite")
        api_inst.create_connection.assert_not_called()
        scan_cls.assert_not_called()

    def test_create_password_stdin_pipe_injects(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_MYSQL_CFG_NO_PW)  # no password key
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Sensors_DB",
                        "--config-file", cfg_path,
                        "--password-stdin",
                        "--no-scan",
                    ],
                    input="secret123\n",
                )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.create_connection.assert_called_once()
        kwargs = api_inst.create_connection.call_args.kwargs
        # config kwarg is the dict (after _resolve_password injection).
        self.assertEqual(kwargs["config"]["password"], "secret123")

    def test_create_password_stdin_empty_pipe_no_inject(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)  # no password key
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--password-stdin",
                        "--no-scan",
                    ],
                    input="\n",
                )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.create_connection.assert_called_once()
        kwargs = api_inst.create_connection.call_args.kwargs
        self.assertNotIn("password", kwargs["config"])

    def test_create_password_tty_prompts_when_no_flag(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_MYSQL_CFG_NO_PW)  # no password key
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                # NOTE: CliRunner replaces sys.stdin during invoke(), undoing any
                # direct sys.stdin patch. Replace the whole cmd_db_conn.sys
                # module reference so the helper's sys.stdin.isatty() lookup
                # goes through our mock chain instead of click's pipe.
                fake_sys = MagicMock()
                fake_sys.stdin.isatty.return_value = True
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys", fake_sys,
                ), patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.typer.prompt",
                    return_value="tty-prompted-pw",
                ) as prompt_mock:
                    result = _runner().invoke(
                        app,
                        [
                            "db-conn", "create",
                            "--name", "Sensors_DB",
                            "--config-file", cfg_path,
                            "--no-scan",
                        ],
                    )
                prompt_mock.assert_called_once()
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.create_connection.assert_called_once()
        kwargs = api_inst.create_connection.call_args.kwargs
        self.assertEqual(kwargs["config"]["password"], "tty-prompted-pw")

    def test_create_no_password_no_tty_passes_through_for_sqlite(self) -> None:
        """Smoke path: subprocess + SQLite fixture + no flag = pass-through."""
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
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
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.create_connection.assert_called_once()
        kwargs = api_inst.create_connection.call_args.kwargs
        self.assertNotIn("password", kwargs["config"])

    def test_create_jwe_password_in_config_refused(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_MYSQL_CFG_NO_PW)
        cfg["password"] = {
            "data": {
                "ciphertext": "X", "encrypted_key": "X", "iv": "X",
                "protected": "X", "tag": "X",
            },
            "type": "Embedded",
        }
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Sensors_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop()
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("JWE credential", combined)
        self.assertIn("/web/config/databases.connections", combined)
        api_inst.create_connection.assert_not_called()

    def test_create_outer_backup_config_refused_with_d04_hint(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_MYSQL_CFG_NO_PW)
        cfg["backupConfig"] = {
            "driver": "SQLite",
            "translator": "SQLITE",
            "connectURL": "jdbc:sqlite:bak.db",
        }
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "create",
                        "--name", "Sensors_DB",
                        "--config-file", cfg_path,
                        "--no-scan",
                    ],
                )
            finally:
                stop()
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("backupConfig", combined)
        self.assertIn("not supported by the SDK", combined)
        api_inst.create_connection.assert_not_called()

    def test_create_inner_backup_configneric_reject(self) -> None:
        """When backupConfig is NOT at the top of the config-file (e.g., nested
        deeper or otherwise slipped past the pop), ConnectionConfig.extra='forbid'
        catches it with a generic 'extra fields' message (no backupConfig Hint).

        Simulated: monkeypatch _read_config to return a config_dict whose
        top-level pop has already happened (so backupConfig is still present
        but the pop misses it). In practice this would happen if backupConfig
        were nested inside an unmodeled subkey. For testing, we directly
        deliver a dict where backupConfig sits among the 25 fields but the
        pop will remove it, so a true 'inner' test instead injects an extra
        unknown key that ConnectionConfig forbids generically.
        """
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        # Inject an extra non-modeled field at the inner level. Confirms
        # extra="forbid" surfaces as a generic ValidationError (not the
        # backupConfig Hint).
        cfg["someUnknownField"] = "x"
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
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
                stop()
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        # Generic message — no backupConfig Hint.
        self.assertNotIn("not supported by the SDK", combined)
        # pydantic emits 'extra_forbidden' or 'extra fields not permitted' depending on version.
        lowered = combined.lower()
        self.assertTrue(
            "extra" in lowered and ("forbid" in lowered or "not permitted" in lowered),
            msg=f"expected generic extra-fields message in stderr; got: {combined!r}",
        )
        api_inst.create_connection.assert_not_called()

    def test_create_unknown_driver_validation(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_MYSQL_CFG_NO_PW)  # driver=MySQL
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            # Only SQLite installed.
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli(
                driver_list=[{"name": "SQLite", "enabled": True}]
            )
            try:
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
                    result = _runner().invoke(
                        app,
                        [
                            "db-conn", "create",
                            "--name", "Sensors_DB",
                            "--config-file", cfg_path,
                            "--no-scan",
                        ],
                    )
            finally:
                stop()
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("driver 'MySQL' not installed", combined)
        api_inst.create_connection.assert_not_called()

    def test_create_scan_default_invokes_scan(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, scan_cls, scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
                    result = _runner().invoke(
                        app,
                        [
                            "db-conn", "create",
                            "--name", "Demo_DB",
                            "--config-file", cfg_path,
                        ],
                    )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        scan_cls.assert_called_once()
        scan_inst.scan_config.assert_called_once()

    def test_create_no_scan_skips_scan(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
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
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        scan_cls.assert_not_called()

    def test_create_scan_warning_becomes_stderr_warning_exit_0(self) -> None:
        from ignition_gen_sdk.backends.scan_client import ScanWarning
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, scan_cls, scan_inst, stop = _patch_cli()
            try:
                api_inst.create_connection.return_value = {"success": True}
                scan_inst.scan_config.side_effect = ScanWarning("boom")
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
                    result = _runner().invoke(
                        app,
                        [
                            "db-conn", "create",
                            "--name", "Demo_DB",
                            "--config-file", cfg_path,
                        ],
                    )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        self.assertIn("WARNING:", result.stderr)


# ---------------------------------------------------------------------------
# Update verb
# ---------------------------------------------------------------------------

class TestUpdateVerb(unittest.TestCase):
    def test_update_two_call_pattern(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.get_connection.return_value = {"signature": "sig123"}
                api_inst.update_connection.return_value = {"success": True}
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
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
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.get_connection.assert_called_once_with("Demo_DB")
        api_inst.update_connection.assert_called_once()
        args = api_inst.update_connection.call_args
        self.assertEqual(args.args[0], "Demo_DB")
        self.assertEqual(args.args[1], "sig123")
        self.assertIn("config", args.kwargs)

    def test_update_dry_run_no_http(self) -> None:
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                result = _runner().invoke(
                    app,
                    [
                        "db-conn", "update",
                        "--name", "Demo_DB",
                        "--config-file", cfg_path,
                        "--dry-run",
                    ],
                )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.get_connection.assert_not_called()
        api_inst.update_connection.assert_not_called()

    def test_update_not_found_message(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.cli import app
        cfg = dict(_SQLITE_CFG)
        with tempfile.TemporaryDirectory() as td:
            cfg_path = _write_cfg(td, cfg)
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.get_connection.side_effect = PayloadError("404 not found")
                with patch(
                    "ignition_gen_sdk.cli.cmd_db_conn.sys.stdin"
                ) as stdin_mock:
                    stdin_mock.isatty.return_value = False
                    result = _runner().invoke(
                        app,
                        [
                            "db-conn", "update",
                            "--name", "NoSuch",
                            "--config-file", cfg_path,
                            "--no-scan",
                        ],
                    )
            finally:
                stop()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("connection 'NoSuch' not found.", result.stderr)
        api_inst.update_connection.assert_not_called()


# ---------------------------------------------------------------------------
# Delete verb
# ---------------------------------------------------------------------------

class TestDeleteVerb(unittest.TestCase):
    def test_delete_yes_skips_confirmation(self) -> None:
        from ignition_gen_sdk.cli import app
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.get_connection.return_value = {"signature": "sig123"}
            api_inst.delete_connection.return_value = {"success": True}
            result = _runner().invoke(
                app,
                ["db-conn", "delete", "--name", "Demo_DB", "--yes", "--no-scan"],
            )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.delete_connection.assert_called_once_with("Demo_DB", "sig123")

    def test_delete_no_yes_prompts(self) -> None:
        from ignition_gen_sdk.cli import app
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.get_connection.return_value = {"signature": "sig123"}
            api_inst.delete_connection.return_value = {"success": True}
            result = _runner().invoke(
                app,
                ["db-conn", "delete", "--name", "Demo_DB", "--no-scan"],
                input="y\n",
            )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.delete_connection.assert_called_once()

    def test_delete_no_yes_abort(self) -> None:
        from ignition_gen_sdk.cli import app
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            result = _runner().invoke(
                app,
                ["db-conn", "delete", "--name", "Demo_DB", "--no-scan"],
                input="n\n",
            )
        finally:
            stop()
        # typer.confirm(..., abort=True) raises typer.Abort which exits non-zero.
        self.assertNotEqual(result.exit_code, 0)
        api_inst.delete_connection.assert_not_called()


# ---------------------------------------------------------------------------
# Bulk + rename
# ---------------------------------------------------------------------------

class TestBulkAndRenameVerbs(unittest.TestCase):
    def test_delete_bulk_reads_entries(self) -> None:
        from ignition_gen_sdk.cli import app
        entries = [{"name": "X", "signature": "abc"}, {"name": "Y", "signature": "def"}]
        with tempfile.TemporaryDirectory() as td:
            entries_path = _write_cfg(td, entries, name="entries.json")  # type: ignore[arg-type]
            _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
            try:
                api_inst.delete_connections.return_value = {"success": True, "count": 2}
                result = _runner().invoke(
                    app,
                    ["db-conn", "delete-bulk", "--entries-file", entries_path],
                )
            finally:
                stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.delete_connections.assert_called_once_with(entries)

    def test_rename_calls_api(self) -> None:
        from ignition_gen_sdk.cli import app
        _api_cls, api_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            api_inst.rename_connection.return_value = {"success": True}
            result = _runner().invoke(
                app,
                ["db-conn", "rename", "--name", "Old", "--new-name", "New"],
            )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        api_inst.rename_connection.assert_called_once_with("Old", "New")


if __name__ == "__main__":
    unittest.main()
