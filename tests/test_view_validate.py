"""Tests for the runtime-validation helpers + `ign view validate` CLI.

The harness core (validate()) drives a real headless browser, so it is NOT
exercised here; instead the PURE logic (client_url URL resolution, verdict
classification, warnings) is tested directly, and the CLI command is tested
with validate() mocked — covering target resolution, exit codes (0 ok / 1 fail
/ 2 missing-dep), and warning surfacing without launching a browser.

Test IDs:
  - test_client_url_project / _project_page / _client_path / _url / _none_raises / _base_strip
  - test_verdict_clean_ok / _crash_fails / _login_wall_warns / _http_error_fails
  - test_warnings_quality_overlay / _console_errors / _clean_empty
  - test_validate_cmd_no_target_exits_1
  - test_validate_cmd_clean_exits_0
  - test_validate_cmd_crash_exits_1
  - test_validate_cmd_missing_playwright_exits_2
  - test_validate_cmd_quality_overlay_warns_exit_0
  - test_validate_cmd_help
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import unittest
from unittest.mock import patch


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


class TestClientUrl(unittest.TestCase):
    def test_client_url_project(self):
        from ignition_gen_sdk.validation.runtime import client_url
        self.assertEqual(
            client_url(GATEWAY_URL, project="Demo"),
            f"{GATEWAY_URL}/data/perspective/client/Demo",
        )

    def test_client_url_project_page(self):
        from ignition_gen_sdk.validation.runtime import client_url
        self.assertEqual(
            client_url(GATEWAY_URL, project="Demo", page="pid"),
            f"{GATEWAY_URL}/data/perspective/client/Demo/pid",
        )

    def test_client_url_client_path(self):
        from ignition_gen_sdk.validation.runtime import client_url
        self.assertEqual(
            client_url(GATEWAY_URL, client_path="/data/perspective/client/X/y"),
            f"{GATEWAY_URL}/data/perspective/client/X/y",
        )

    def test_client_url_url(self):
        from ignition_gen_sdk.validation.runtime import client_url
        # Absolute --url wins over everything.
        self.assertEqual(
            client_url(GATEWAY_URL, project="Ignored", url=f"{GATEWAY_URL}/abs"),
            f"{GATEWAY_URL}/abs",
        )

    def test_client_url_none_raises(self):
        from ignition_gen_sdk.validation.runtime import client_url
        with self.assertRaises(ValueError):
            client_url(GATEWAY_URL)

    def test_client_url_base_strip(self):
        from ignition_gen_sdk.validation.runtime import client_url
        # Trailing slash on base must not produce a double slash.
        self.assertEqual(
            client_url(f"{GATEWAY_URL}/", project="P"),
            f"{GATEWAY_URL}/data/perspective/client/P",
        )


class TestVerdict(unittest.TestCase):
    def test_verdict_clean_ok(self):
        from ignition_gen_sdk.validation.runtime import verdict
        ok, reasons = verdict(
            {"http_status": 200, "login_wall": False, "component_crashes": 0,
             "quality_error_overlays": 0}
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_verdict_crash_fails(self):
        from ignition_gen_sdk.validation.runtime import verdict
        ok, reasons = verdict(
            {"http_status": 200, "component_crashes": 3,
             "crashed_components": ["ia.display.icon", None]}
        )
        self.assertFalse(ok)
        self.assertTrue(any("crash" in r for r in reasons))
        self.assertTrue(any("ia.display.icon" in r for r in reasons))

    def test_verdict_login_wall_warns_but_does_not_fail(self):
        # A login wall is a WARNING, not a failure. An anonymous Perspective
        # session offers its own "Sign in" affordance, and any page that edits
        # credentials has a password box on it, so the pair is not evidence of
        # a wall -- it made every user-management page fail validation. A real
        # wall renders no view at all, which view_state_messages catches.
        from ignition_gen_sdk.validation.runtime import verdict, warnings

        payload = {"http_status": 200, "login_wall": True, "component_crashes": 0}
        ok, reasons = verdict(payload)
        self.assertTrue(ok, msg=reasons)
        self.assertTrue(any("login wall" in w for w in warnings(payload)))

    def test_verdict_http_error_fails(self):
        from ignition_gen_sdk.validation.runtime import verdict
        ok, reasons = verdict({"http_status": 404, "component_crashes": 0})
        self.assertFalse(ok)
        self.assertTrue(any("404" in r for r in reasons))

    def test_verdict_quality_overlay_not_a_failure(self):
        from ignition_gen_sdk.validation.runtime import verdict
        # Bad data quality is a SIGNAL, not a view defect → still ok.
        ok, _ = verdict(
            {"http_status": 200, "component_crashes": 0, "quality_error_overlays": 12}
        )
        self.assertTrue(ok)

    def test_verdict_view_not_found_fails(self):
        # A URL the router cannot resolve renders Perspective's own placeholder
        # card: HTTP 200, zero crashes, zero overlays — used to print "OK:".
        from ignition_gen_sdk.validation.runtime import verdict
        ok, reasons = verdict({
            "http_status": 200, "component_crashes": 0, "quality_error_overlays": 0,
            "view_state_messages": ["View Not Found"],
        })
        self.assertFalse(ok)
        self.assertTrue(any("did not resolve" in r for r in reasons))

    def test_verdict_benign_view_state_message_ok(self):
        # Transient/benign placeholders (e.g. "Loading...") are not failures.
        from ignition_gen_sdk.validation.runtime import verdict
        ok, _ = verdict({
            "http_status": 200, "component_crashes": 0,
            "view_state_messages": ["Loading..."],
        })
        self.assertTrue(ok)

    def test_verdict_negative_crashes_inconclusive_fails(self):
        # Harness sets -1 when the crash-boundary selector threw. An
        # inconclusive crash check must FAIL, never silently read as "clean".
        from ignition_gen_sdk.validation.runtime import verdict
        ok, reasons = verdict({"http_status": 200, "component_crashes": -1})
        self.assertFalse(ok)
        self.assertTrue(any("inconclusive" in r for r in reasons))


class TestWarnings(unittest.TestCase):
    def test_warnings_quality_overlay(self):
        from ignition_gen_sdk.validation.runtime import warnings
        w = warnings({"quality_error_overlays": 12})
        self.assertTrue(any("quality" in x for x in w))

    def test_warnings_console_errors(self):
        from ignition_gen_sdk.validation.runtime import warnings
        w = warnings({"console_errors": ["boom", "bang"]})
        self.assertTrue(any("console" in x for x in w))

    def test_warnings_clean_empty(self):
        from ignition_gen_sdk.validation.runtime import warnings
        self.assertEqual(warnings({"quality_error_overlays": 0, "console_errors": []}), [])

    def test_warnings_negative_quality_detector_errored(self):
        from ignition_gen_sdk.validation.runtime import warnings
        w = warnings({"quality_error_overlays": -1})
        self.assertTrue(any("detector errored" in x for x in w))

    def test_warnings_symbol_svg_empty_named_not_fatal(self):
        # An empty ia.symbol.* svg is the IA session-settle race,
        # reported by name so it is not chased as a view defect; never a failure.
        from ignition_gen_sdk.validation.runtime import verdict, warnings
        payload = dict(_CLEAN, symbol_svg_empty=6)
        w = warnings(payload)
        self.assertTrue(any("EMPTY" in x and "not a view defect" in x for x in w))
        self.assertTrue(verdict(payload)[0])
        self.assertEqual(warnings(dict(_CLEAN, symbol_svg_empty=0)), [])


_CLEAN = {
    "url": f"{GATEWAY_URL}/data/perspective/client/Demo",
    "http_status": 200, "login_wall": False, "component_crashes": 0,
    "quality_error_overlays": 0, "crashed_components": [],
    "console_errors": [], "page_errors": [], "screenshot": "/tmp/x.png",
    "visible_text_sample": "hello",
}


class TestValidateCmd(unittest.TestCase):
    def test_validate_cmd_no_target_exits_1(self):
        from ignition_gen_sdk.cli import app
        res = _runner().invoke(app, ["view", "validate"])
        self.assertEqual(res.exit_code, 1)

    def test_validate_cmd_clean_exits_0(self):
        from ignition_gen_sdk.cli import app
        with patch("ignition_gen_sdk.validation.runtime.validate", return_value=dict(_CLEAN)):
            res = _runner().invoke(app, ["view", "validate", "--project", "Demo"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("OK:", res.output)

    def test_validate_cmd_crash_exits_1(self):
        from ignition_gen_sdk.cli import app
        crashed = dict(_CLEAN, component_crashes=3, crashed_components=["ia.display.icon"])
        with patch("ignition_gen_sdk.validation.runtime.validate", return_value=crashed):
            res = _runner().invoke(app, ["view", "validate", "--project", "Demo", "--page", "pid"])
        self.assertEqual(res.exit_code, 1, res.output)
        self.assertIn("FAIL", res.output)

    def test_validate_cmd_missing_playwright_exits_2(self):
        from ignition_gen_sdk.cli import app
        from ignition_gen_sdk.validation.runtime import RuntimeValidationError
        with patch(
            "ignition_gen_sdk.validation.runtime.validate",
            side_effect=RuntimeValidationError("Playwright is required ... pip install -e '.[runtime]'"),
        ):
            res = _runner().invoke(app, ["view", "validate", "--project", "Demo"])
        self.assertEqual(res.exit_code, 2, res.output)

    def test_validate_cmd_quality_overlay_warns_exit_0(self):
        from ignition_gen_sdk.cli import app
        noisy = dict(_CLEAN, quality_error_overlays=12)
        with patch("ignition_gen_sdk.validation.runtime.validate", return_value=noisy):
            res = _runner().invoke(app, ["view", "validate", "--client-path", "/data/perspective/client/Demo/pid"])
        self.assertEqual(res.exit_code, 0, res.output)
        # Quality overlays warn but do not fail.
        self.assertIn("WARNING", res.output)
        self.assertIn("OK:", res.output)

    def test_validate_cmd_help(self):
        from ignition_gen_sdk.cli import app
        res = _runner().invoke(app, ["view", "validate", "--help"])
        self.assertEqual(res.exit_code, 0)
        self.assertIn("--project", res.output)
        self.assertIn("--page", res.output)

    def test_validate_cmd_help_shows_runtime_extra(self):
        # Rich markup silently strips '[runtime]' from --help
        # (it parses the brackets as a style tag) unless escaped → a fresh user
        # is told to `pip install -e '.'` (no extra → no Playwright → verb fails).
        # The docstring escapes it (\\[) so help must render the literal extra.
        from ignition_gen_sdk.cli import app
        res = _runner().invoke(app, ["view", "validate", "--help"])
        self.assertIn("[runtime]", res.output)
        # And the --project/--page → --client-path shorthand the clean-room user wanted.
        self.assertIn("shorthand", res.output)


if __name__ == "__main__":
    unittest.main()
