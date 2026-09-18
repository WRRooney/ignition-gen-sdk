"""``ign api --strict`` deep-validation tests.

Tests gated on the [strict] extras being installed (``pytest.importorskip``).
When openapi_core is unavailable, all tests in this module are SKIPPED with
a clear reason -- the lean default install path is preserved.

Behavior contracts:

- test_strict_passes_when_body_valid: real spec path with a valid body
  passes --strict; client.request IS called (mocked); exit 0.
- test_strict_fails_with_pointer_in_message: invalid body -> exit 1
  with ``Payload error:`` AND a JSON pointer (e.g. ``$`` or ``$.name``)
  in stderr; client.request NOT called.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json
import unittest
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Skip the entire module if openapi-core not installed.
pytest.importorskip(
    "openapi_core",
    reason="--strict requires the [strict] extras: pip install -e tools/ignition_gen_sdk[strict]",
)


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


def _make_response(status: int, body: dict | list | None = None) -> httpx.Response:
    text = "" if body is None else json.dumps(body)
    return httpx.Response(
        status_code=status,
        content=text.encode("utf-8"),
        request=httpx.Request("GET", f"{GATEWAY_URL}/test"),
    )


class TestStrictMode(unittest.TestCase):
    def test_strict_passes_when_body_valid(self) -> None:
        """Valid POST body for /data/api/v1/projects passes --strict; HTTP fires.

        /data/api/v1/projects accepts an object with a required `name`
        property (per ignition_openapi.json). Pass {"name": "DewSmoke"} --
        strict validator must allow this; client.request gets called.
        """
        from ignition_gen_sdk.cli import app

        body = json.dumps({"name": "DewSmoke"})
        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_inst.request.return_value = _make_response(200, {"ok": True})
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                [
                    "api", "POST", "/data/api/v1/projects",
                    "--json", body,
                    "--strict",
                    "--confirm",  # suppress non-GET tty prompt
                ],
            )

        self.assertEqual(
            result.exit_code,
            0,
            msg=f"stderr={result.stderr!r} stdout={result.stdout!r}",
        )
        client_inst.request.assert_called_once()

    def test_strict_fails_with_pointer_in_message(self) -> None:
        """Invalid body (missing required 'name') surfaces JSON pointer in stderr.

        Per ignition_openapi.json, /data/api/v1/projects POST requires
        `name`. Empty body {} should fail strict validation with the
        underlying jsonschema $ json_path (root-level required field).
        """
        from ignition_gen_sdk.cli import app

        with patch("ignition_gen_sdk.cli.cmd_api.IgnitionAPIClient") as client_cls:
            client_inst = MagicMock()
            client_cls.return_value = client_inst
            result = _runner().invoke(
                app,
                [
                    "api", "POST", "/data/api/v1/projects",
                    "--json", "{}",
                    "--strict",
                    "--confirm",
                ],
            )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Payload error:", result.stderr)
        self.assertIn("strict validation failed", result.stderr)
        # JSON pointer marker -- $ for root, $.field for nested; either is acceptable
        self.assertTrue(
            "$" in result.stderr,
            msg=f"expected JSON pointer marker '$' in stderr; got: {result.stderr!r}",
        )
        client_inst.request.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
