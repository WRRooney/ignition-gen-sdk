"""Tests for `ign logs` — the gateway-log runtime-debugging verb.

Mocks IgnitionAPIClient so no live gateway is needed: asserts the query the verb
builds (search/min-level/logger/limit/since-min), the formatted output, --json,
and --stack (ERROR stack lines).
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch, MagicMock


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


def _fake_client(items):
    """A fake IgnitionAPIClient whose .request() records the path and returns items."""
    captured = {}

    class _Resp:
        text = json.dumps({"items": items})
        def json(self):
            return {"items": items}

    class _Client:
        def __init__(self, settings):
            pass
        def request(self, method, path, **kw):
            captured["method"] = method
            captured["path"] = path
            return _Resp()
        def close(self):
            pass

    return _Client, captured


_ITEMS = [
    {"timestamp": 1000, "level": "ERROR", "loggerName": "app.nav",
     "message": "Could not initialize project script module 'app.nav'",
     "stack": ["TypeError: foo", "  at bar", "  at baz"]},
    {"timestamp": 900, "level": "INFO", "loggerName": "x", "message": "ok"},
]


def _invoke(args, items=_ITEMS):
    Client, captured = _fake_client(items)
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy"}, clear=False), \
         patch("ignition_gen_sdk.cli.cmd_logs.IgnitionAPIClient", Client), \
         patch("ignition_gen_sdk.cli.cmd_logs.Settings", MagicMock(return_value=object())):
        from ignition_gen_sdk.cli import app
        res = _runner().invoke(app, ["logs"] + args)
    return res, captured


class TestLogsCmd(unittest.TestCase):
    def test_builds_query_from_options(self):
        res, cap = _invoke(["--search", "app.nav", "--min-level", "error", "--logger", "app.nav", "--limit", "7"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertTrue(cap["path"].startswith("/data/api/v1/logs?"))
        self.assertIn("search=app.nav", cap["path"])
        self.assertIn("minLevel=ERROR", cap["path"])     # upper-cased
        self.assertIn("logger=app.nav", cap["path"])
        self.assertIn("limit=7", cap["path"])

    def test_since_min_adds_starttime(self):
        res, cap = _invoke(["--since-min", "10"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("startTime=", cap["path"])

    def test_formatted_output(self):
        res, _ = _invoke(["--limit", "5"])
        self.assertIn("ERROR", res.output)
        self.assertIn("app.nav", res.output)
        self.assertIn("Could not initialize", res.output)

    def test_stack_only_with_flag(self):
        res_no, _ = _invoke(["--limit", "5"])
        self.assertNotIn("TypeError: foo", res_no.output)
        res_yes, _ = _invoke(["--limit", "5", "--stack"])
        self.assertIn("TypeError: foo", res_yes.output)

    def test_json_mode(self):
        res, _ = _invoke(["--json"])
        data = json.loads(res.output)
        self.assertEqual(data[0]["loggerName"], "app.nav")

    def test_empty(self):
        res, _ = _invoke(["--search", "nope"], items=[])
        self.assertIn("no matching log entries", res.output)

    def test_help(self):
        res, _ = _invoke(["--help"])
        self.assertEqual(res.exit_code, 0)
        self.assertIn("--search", res.output)


if __name__ == "__main__":
    unittest.main()
