"""``ign driver`` CLI tests.

Behavior contracts:

- ``ign driver list`` prints JSON listing all installed drivers
  ``[{name, enabled}, ...]`` to stdout; exit 0.
- ``ign driver describe <name>`` prints JSON driver dict
  (with at least ``defaultTranslator``) to stdout; exit 0.
- 404 / not-found on describe yields ``Error: driver '<name>' not found.``
  on stderr; exit 1.

Tests patch ``ignition_gen_sdk.cli.cmd_driver.ApiBackend`` (the class as
imported into cmd_driver) so the live gateway is not contacted. The
underlying ``IgnitionAPIClient`` is also patched indirectly because
``_get_api`` instantiates it before calling ApiBackend — to keep the
mock surface narrow, we patch ``ApiBackend`` itself.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


def _runner():
    from typer.testing import CliRunner

    # Typer 0.25.x / Click 8.2+ — CliRunner separates stdout/stderr.
    return CliRunner()


class TestCliWiring(unittest.TestCase):
    """Top-level + subgroup wiring."""

    def test_top_level_help_lists_driver_subcommand(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("driver", result.output)

    def test_driver_help_lists_list_and_describe(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["driver", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("list", result.output)
        self.assertIn("describe", result.output)


class TestDriverList(unittest.TestCase):
    """``ign driver list`` prints JSON list of installed drivers."""

    def test_driver_list_prints_json(self) -> None:
        from ignition_gen_sdk.cli import app

        fake = [
            {"name": "SQLite", "enabled": True},
            {"name": "MySQL", "enabled": True},
        ]
        with patch(
            "ignition_gen_sdk.cli.cmd_driver.ApiBackend"
        ) as api_cls, patch(
            "ignition_gen_sdk.cli.cmd_driver.IgnitionAPIClient"
        ):
            api_inst = MagicMock()
            api_inst.list_drivers.return_value = fake
            api_cls.return_value = api_inst

            result = _runner().invoke(app, ["driver", "list"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed, fake)
        api_inst.list_drivers.assert_called_once()


class TestDriverDescribe(unittest.TestCase):
    """``ign driver describe <name>`` prints driver config dict."""

    def test_driver_describe_returns_metadata(self) -> None:
        from ignition_gen_sdk.cli import app

        fake = {
            "type": "SQLITE",
            "classname": "org.sqlite.JDBC",
            "defaultTranslator": "SQLITE",
            "defaultValidationQuery": "SELECT 1",
            "urlFormat": "jdbc:sqlite:<path>",
            "urlInstructions": "Path to .db file",
        }
        with patch(
            "ignition_gen_sdk.cli.cmd_driver.ApiBackend"
        ) as api_cls, patch(
            "ignition_gen_sdk.cli.cmd_driver.IgnitionAPIClient"
        ):
            api_inst = MagicMock()
            api_inst.get_driver.return_value = fake
            api_cls.return_value = api_inst

            result = _runner().invoke(app, ["driver", "describe", "SQLite"])

        self.assertEqual(result.exit_code, 0, msg=result.output)
        parsed = json.loads(result.stdout)
        self.assertIn("defaultTranslator", parsed)
        self.assertEqual(parsed["defaultTranslator"], "SQLITE")
        # The CLI must pass the literal name through to the backend
        api_inst.get_driver.assert_called_once_with("SQLite")

    def test_driver_describe_404(self) -> None:
        """PayloadError with 'not found' → clean error + exit 1."""
        from ignition_gen_sdk.backends.api_client import PayloadError
        from ignition_gen_sdk.cli import app

        with patch(
            "ignition_gen_sdk.cli.cmd_driver.ApiBackend"
        ) as api_cls, patch(
            "ignition_gen_sdk.cli.cmd_driver.IgnitionAPIClient"
        ):
            api_inst = MagicMock()
            api_inst.get_driver.side_effect = PayloadError(
                "404 Not Found: driver 'NoSuchDriver' not found"
            )
            api_cls.return_value = api_inst

            result = _runner().invoke(
                app, ["driver", "describe", "NoSuchDriver"]
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("driver 'NoSuchDriver' not found.", result.stderr)
        # Token MUST NOT appear in error output.
        self.assertNotIn("test-secret-DO-NOT-LEAK", result.stderr)
