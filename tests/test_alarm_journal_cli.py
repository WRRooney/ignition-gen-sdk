"""``ign alarm-journal`` CLI tests.

Mirrors tests/test_cli_db_conn.py patterns.

Patch ``ignition_gen_sdk.cli.cmd_alarm_journal.IgnitionAPIClient`` (the class
as imported into the cmd module) so the live gateway is never contacted. Also
patch ``ScanClient`` (instantiated in _scan_after_mutation).

Behavior contracts:

- 3 verbs (create / list / get) wired and discoverable; --help works.
- ``create``:
    * Wraps the body in a JSON ARRAY; payload[0].config.profile.type == "DATASOURCE"
      and payload[0].config.settings.datasource == the given --datasource.
    * --dry-run prints the array; no HTTP, no scan.
    * Posts to the resources "(multiple)" path with allowInvalidReferences=true.
    * --no-scan → ScanClient never instantiated.
    * Invalid --min-priority → ValueError → exit 1; no HTTP call.
- ``list`` GETs /data/api/v1/resources/list/ignition/alarm-journal.
- ``get`` GETs /data/api/v1/resources/find/ignition/alarm-journal/<name>;
  404 → "alarm journal '<name>' not found."
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


def _patch_cli():
    """Patch IgnitionAPIClient + ScanClient on the cmd module.

    Returns (client_cls, client_inst, scan_cls, scan_inst, stop_all).
    The client's .request() returns a MagicMock response whose .json() and
    .text are configurable per test.
    """
    client_cls_p = patch("ignition_gen_sdk.cli.cmd_alarm_journal.IgnitionAPIClient")
    scan_cls_p = patch("ignition_gen_sdk.cli.cmd_alarm_journal.ScanClient")

    client_cls = client_cls_p.start()
    scan_cls = scan_cls_p.start()

    client_inst = MagicMock()
    # Default response: a JSON object that round-trips through .json().
    resp = MagicMock()
    resp.text = "{}"
    resp.json.return_value = {"ok": True}
    client_inst.request.return_value = resp
    client_cls.return_value = client_inst

    scan_inst = MagicMock()
    scan_cls.return_value.__enter__.return_value = scan_inst
    scan_cls.return_value.__exit__.return_value = False

    def stop_all():
        client_cls_p.stop()
        scan_cls_p.stop()

    return client_cls, client_inst, scan_cls, scan_inst, stop_all


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

class TestCliWiring(unittest.TestCase):
    def test_top_level_help_lists_alarm_journal(self) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("alarm-journal", result.output)

    def test_alarm_journal_help_lists_all_verbs(self) -> None:
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["alarm-journal", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        for verb in ("create", "list", "get"):
            self.assertIn(verb, result.output, msg=f"verb {verb} missing")


# ---------------------------------------------------------------------------
# Create verb
# ---------------------------------------------------------------------------

class TestCreateVerb(unittest.TestCase):
    def test_create_wraps_body_in_json_array(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            with patch(
                "ignition_gen_sdk.cli.cmd_alarm_journal.sys.stdin"
            ) as stdin_mock:
                stdin_mock.isatty.return_value = False
                result = _runner().invoke(
                    app,
                    [
                        "alarm-journal", "create",
                        "--name", "MainJournal",
                        "--datasource", "Demo_DB",
                        "--no-scan",
                    ],
                )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        client_inst.request.assert_called_once()
        args = client_inst.request.call_args
        # Positional: method, path. Body is in the `json` kwarg.
        self.assertEqual(args.args[0], "POST")
        self.assertIn("allowInvalidReferences=true", args.args[1])
        body = args.kwargs["json"]
        # CRITICAL: body must be a JSON ARRAY (resources "(multiple)" pattern).
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 1)
        obj = body[0]
        self.assertEqual(obj["name"], "MainJournal")
        self.assertEqual(obj["config"]["profile"]["type"], "DATASOURCE")
        self.assertEqual(obj["config"]["settings"]["datasource"], "Demo_DB")

    def test_create_dry_run_no_http_no_scan(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, scan_cls, _scan_inst, stop = _patch_cli()
        try:
            result = _runner().invoke(
                app,
                [
                    "alarm-journal", "create",
                    "--name", "DryJournal",
                    "--datasource", "Sensors_DB",
                    "--dry-run",
                ],
            )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        # dry-run prints the array-wrapped payload.
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["config"]["profile"]["type"], "DATASOURCE")
        self.assertEqual(payload[0]["config"]["settings"]["datasource"], "Sensors_DB")
        client_inst.request.assert_not_called()
        scan_cls.assert_not_called()

    def test_create_defaults_applied(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            with patch(
                "ignition_gen_sdk.cli.cmd_alarm_journal.sys.stdin"
            ) as stdin_mock:
                stdin_mock.isatty.return_value = False
                result = _runner().invoke(
                    app,
                    [
                        "alarm-journal", "create",
                        "--name", "J",
                        "--datasource", "DS",
                        "--no-scan",
                    ],
                )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        obj = client_inst.request.call_args.kwargs["json"][0]
        settings = obj["config"]["settings"]
        self.assertEqual(settings["events"]["minPriority"], "Diagnostic")
        self.assertEqual(settings["pruning"]["age"], 90)
        self.assertEqual(settings["pruning"]["ageUnits"], "DAY")
        self.assertEqual(settings["advanced"]["tableName"], "alarm_events")
        self.assertEqual(settings["advanced"]["dataTableName"], "alarm_event_data")

    def test_create_no_scan_skips_scan(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, _client_inst, scan_cls, _scan_inst, stop = _patch_cli()
        try:
            with patch(
                "ignition_gen_sdk.cli.cmd_alarm_journal.sys.stdin"
            ) as stdin_mock:
                stdin_mock.isatty.return_value = False
                result = _runner().invoke(
                    app,
                    [
                        "alarm-journal", "create",
                        "--name", "J",
                        "--datasource", "DS",
                        "--no-scan",
                    ],
                )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        scan_cls.assert_not_called()

    def test_create_scan_default_invokes_scan(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, _client_inst, scan_cls, scan_inst, stop = _patch_cli()
        try:
            with patch(
                "ignition_gen_sdk.cli.cmd_alarm_journal.sys.stdin"
            ) as stdin_mock:
                stdin_mock.isatty.return_value = False
                result = _runner().invoke(
                    app,
                    [
                        "alarm-journal", "create",
                        "--name", "J",
                        "--datasource", "DS",
                    ],
                )
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        scan_cls.assert_called_once()
        scan_inst.scan_config.assert_called_once()

    def test_create_invalid_min_priority_rejected(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            with patch(
                "ignition_gen_sdk.cli.cmd_alarm_journal.sys.stdin"
            ) as stdin_mock:
                stdin_mock.isatty.return_value = False
                result = _runner().invoke(
                    app,
                    [
                        "alarm-journal", "create",
                        "--name", "J",
                        "--datasource", "DS",
                        "--min-priority", "Bogus",
                        "--no-scan",
                    ],
                )
        finally:
            stop()
        self.assertNotEqual(result.exit_code, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("min-priority", combined)
        client_inst.request.assert_not_called()


# ---------------------------------------------------------------------------
# Read-only verbs
# ---------------------------------------------------------------------------

class TestReadOnlyVerbs(unittest.TestCase):
    def test_list_builds_correct_get_path(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            resp = MagicMock()
            resp.text = "[]"
            resp.json.return_value = [{"name": "MainJournal"}]
            client_inst.request.return_value = resp
            result = _runner().invoke(app, ["alarm-journal", "list"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        client_inst.request.assert_called_once()
        args = client_inst.request.call_args
        self.assertEqual(args.args[0], "GET")
        self.assertEqual(args.args[1], "/data/api/v1/resources/list/ignition/alarm-journal")
        self.assertEqual(json.loads(result.stdout), [{"name": "MainJournal"}])

    def test_get_builds_correct_find_path(self) -> None:
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            resp = MagicMock()
            resp.text = "{}"
            resp.json.return_value = {"name": "MainJournal"}
            client_inst.request.return_value = resp
            result = _runner().invoke(app, ["alarm-journal", "get", "--name", "MainJournal"])
        finally:
            stop()
        self.assertEqual(result.exit_code, 0, msg=result.stdout + (result.stderr or ""))
        args = client_inst.request.call_args
        self.assertEqual(args.args[0], "GET")
        self.assertEqual(
            args.args[1],
            "/data/api/v1/resources/find/ignition/alarm-journal/MainJournal",
        )

    def test_get_not_found_message(self) -> None:
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.cli import app
        _cls, client_inst, _scan_cls, _scan_inst, stop = _patch_cli()
        try:
            client_inst.request.side_effect = PayloadError("404 Not Found")
            result = _runner().invoke(
                app, ["alarm-journal", "get", "--name", "Nope"]
            )
        finally:
            stop()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("alarm journal 'Nope' not found.", result.stderr)


if __name__ == "__main__":
    unittest.main()
