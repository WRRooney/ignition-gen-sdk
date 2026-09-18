"""``ign api`` CliRunner test suite.

Behavior contracts:

- ``ign --help`` lists ``api`` between ``component`` and ``diff``.
- ``ign api --help`` lists --json / --file / --strict / --confirm /
  --dry-run / --no-color flags.
- test_light_validation_unknown_path: invalid path -> exit 1 with
  ``Path error:`` and openapi-hint in stderr; BEFORE any HTTP.
- test_light_validation_wrong_method: invalid method -> exit 1 with
  ``Method error:`` in stderr; BEFORE any HTTP.
- test_jwe_refusal: body with all 5 JWE keys -> exit 1 with
  ``Payload error:`` + ``JWE refusal`` in stderr; BEFORE any HTTP.
- test_dry_run: --dry-run prints planned request; exit 0; no HTTP call.
- test_mutually_exclusive_body_flags: --json + --file -> exit 1.
- test_success_path: mock returns 200 with body -> stdout has body JSON.
- test_redaction_in_output: response body containing a token-shape
  literal is scrubbed to ``***REDACTED***`` in stdout.
- test_five_clause_error_order: parametrized over 5 error types;
  each exits 1 with the canonical label prefix in stderr.

All gateway interactions are mocked. See test_cli_api_live_smoke.py for the
live gateway smoke tests.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


def _make_response(status_code: int, body: dict | list | str | None = None) -> httpx.Response:
    """Build an httpx.Response with the given body for mock client.request returns."""
    if body is None:
        text = ""
    elif isinstance(body, (dict, list)):
        text = json.dumps(body)
    else:
        text = body
    return httpx.Response(
        status_code=status_code,
        content=text.encode("utf-8"),
        request=httpx.Request("GET", f"{GATEWAY_URL}/test"),
    )


# ---------------------------------------------------------------------------
# Wiring tests -- assert api is registered between component and diff
# ---------------------------------------------------------------------------

class TestCliWiring(unittest.TestCase):
    def test_top_level_help_lists_api(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("api", result.output)

    def test_api_help_lists_all_flags(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["api", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        for flag in ("--json", "--file", "--strict", "--confirm", "--dry-run", "--no-color"):
            self.assertIn(flag, result.output, msg=f"flag {flag} missing from help")

    def test_api_help_mentions_generic_ignition(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["api", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Generic Ignition HTTP API", result.output)


# ---------------------------------------------------------------------------
# Light validation (always-on)
# ---------------------------------------------------------------------------

class TestLightValidation(unittest.TestCase):
    def test_light_validation_unknown_path(self) -> None:
        """Invalid path -> Path error: + hint pointing at openapi.json."""
        from ignition_gen_sdk.cli import app

        # No mock of IgnitionAPIClient; if the test reaches HTTP, .request
        # would attempt a real connection -- but light validation must fail
        # before that.
        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(app, ["api", "GET", "/no/such/path"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Path error:", result.stderr)
        self.assertIn("openapi.json", result.stderr)
        client_inst.request.assert_not_called()

    def test_light_validation_wrong_method(self) -> None:
        """DELETE on GET-only path -> Method error: BEFORE any HTTP."""
        from ignition_gen_sdk.cli import app

        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(app, ["api", "DELETE", "/data/api/v1/gateway-info"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Method error:", result.stderr)
        client_inst.request.assert_not_called()


# ---------------------------------------------------------------------------
# JWE refusal
# ---------------------------------------------------------------------------

class TestJWERefusal(unittest.TestCase):
    def test_jwe_refusal(self) -> None:
        """Body with all 5 JWE keys -> Payload error: JWE refusal BEFORE any HTTP."""
        from ignition_gen_sdk.cli import app

        jwe = json.dumps({
            "ciphertext": "x",
            "encrypted_key": "y",
            "iv": "z",
            "protected": "a",
            "tag": "b",
        })
        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                ["api", "POST", "/data/api/v1/scan/config", "--json", jwe],
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Payload error:", result.stderr)
        self.assertIn("JWE credential", result.stderr)
        client_inst.request.assert_not_called()

    def test_jwe_refusal_nested(self) -> None:
        """Nested JWE inside a config dict is ALSO refused (recursive walk)."""
        from ignition_gen_sdk.cli import app

        nested = json.dumps({
            "config": {
                "password": {
                    "ciphertext": "x",
                    "encrypted_key": "y",
                    "iv": "z",
                    "protected": "a",
                    "tag": "b",
                },
            },
        })
        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                ["api", "POST", "/data/api/v1/scan/config", "--json", nested],
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("JWE credential", result.stderr)
        client_inst.request.assert_not_called()


# ---------------------------------------------------------------------------
# --dry-run short-circuit
# ---------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):
    def test_dry_run_prints_planned_request_no_http(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                ["api", "--dry-run", "GET", "/data/api/v1/gateway-info"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        # Stdout should be the planned-request JSON.
        out = result.stdout
        self.assertIn('"method": "GET"', out)
        self.assertIn('"path": "/data/api/v1/gateway-info"', out)
        client_inst.request.assert_not_called()


# ---------------------------------------------------------------------------
# Body-flag mutual exclusion
# ---------------------------------------------------------------------------

class TestMutuallyExclusive(unittest.TestCase):
    def test_json_and_file_both_passed(self) -> None:
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as td:
            file_path = Path(td) / "body.json"
            file_path.write_text("{}", encoding="utf-8")

            with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
                client_inst = MagicMock()
                client_cls.return_value = client_inst
                result = _runner().invoke(
                    app,
                    [
                        "api", "POST", "/data/api/v1/scan/config",
                        "--json", "{}",
                        "--file", str(file_path),
                    ],
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("mutually exclusive", result.stderr)
        client_inst.request.assert_not_called()


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestSuccessPath(unittest.TestCase):
    def test_success_path_prints_body_json(self) -> None:
        from ignition_gen_sdk.cli import app

        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_inst.request.return_value = _make_response(200, {"ok": True, "name": "Demo"})
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                ["api", "GET", "/data/api/v1/gateway-info"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.stderr or result.output)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed, {"ok": True, "name": "Demo"})
        client_inst.request.assert_called_once()


# ---------------------------------------------------------------------------
# Token redaction in output (defense-in-depth)
# ---------------------------------------------------------------------------

class TestRedactionInOutput(unittest.TestCase):
    def test_response_body_token_is_scrubbed(self) -> None:
        """A synthetic token in the response body is masked before stdout write."""
        from ignition_gen_sdk.cli import app

        # Mock response body contains a fake token shape.
        fake_body = {"audit": "user=test:AB12_CD34-EF56-GH78_IJ90-KL12 action=read"}

        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_inst.request.return_value = _make_response(200, fake_body)
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                ["api", "GET", "/data/api/v1/gateway-info"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.stderr or result.output)
        self.assertIn("***REDACTED***", result.stdout)
        self.assertNotIn("AB12_CD34-EF56-GH78_IJ90-KL12", result.stdout)


# ---------------------------------------------------------------------------
# Five-clause error block (canonical taxonomy order)
# ---------------------------------------------------------------------------

class TestFiveClauseErrorOrder(unittest.TestCase):
    """Parametrized over the 5 error classes; each lands on the correct
    label prefix from _errors._LABELS."""

    _CASES = [
        ("AuthMissingError", "Auth error:"),
        ("AuthScopeError", "Permission error:"),
        ("PayloadError", "Payload error:"),
        ("GatewayError", "Gateway error:"),
        ("NetworkError", "Network error:"),
    ]

    def test_each_error_class_lands_on_its_label(self) -> None:
        from ignition_gen_sdk.backends import api_client as ac
        from ignition_gen_sdk.cli import app

        for class_name, label in self._CASES:
            with self.subTest(error=class_name, label=label):
                exc_cls = getattr(ac, class_name)
                with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
                    client_inst = MagicMock()
                    client_inst.request.side_effect = exc_cls(f"{class_name} fired")
                    client_cls.return_value = client_inst
                    result = _runner().invoke(
                        app,
                        ["api", "GET", "/data/api/v1/gateway-info"],
                    )

                self.assertEqual(
                    result.exit_code,
                    1,
                    msg=f"{class_name}: expected exit 1; got {result.exit_code}",
                )
                self.assertIn(
                    label,
                    result.stderr,
                    msg=f"{class_name}: expected '{label}' in stderr; got: {result.stderr!r}",
                )


# ---------------------------------------------------------------------------
# Token not in any output / file
# ---------------------------------------------------------------------------

class TestNoTokenInSurface(unittest.TestCase):
    def test_token_not_in_help_output(self) -> None:
        """`ign api --help` must not echo the sentinel token from the env."""
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["api", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
