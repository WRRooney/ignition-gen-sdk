"""Tests for `ign tag import --file` (first-class tags/import verb).

The loop previously hand-built a {"tags":[...]} body and POSTed via raw
`ign api`. `tag import` makes that a first-class verb mirroring
`view write --file`: it reads the file body verbatim and POSTs it through the
SAME httpx client (IgnitionAPIClient.request) the rest of the CLI uses, so the
token never enters argv.

All tests MOCK the HTTP layer (IgnitionAPIClient at the cmd_tag namespace) +
CliRunner — never the live gateway. Contracts:

(a) valid file → success path + correct URL / params on the POST.
(b) missing --file → exit 1 (Typer required-option error).
(c) --dry-run makes NO HTTP call.
(d) --help lists the import command.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _runner():
    from typer.testing import CliRunner

    # Typer 0.25.x CliRunner separates stdout / stderr; result.output is merged.
    return CliRunner()


_IMPORT_BODY = {
    "name": "",
    "tagType": "Provider",
    "tags": [
        {
            "name": "WaterTankLevel",
            "tagType": "AtomicTag",
            "dataType": "Float8",
            "valueSource": "memory",
            "value": 42.0,
        }
    ],
}

_BARE_LIST = [
    {"name": "A", "tagType": "AtomicTag", "dataType": "Int4", "valueSource": "memory"},
    {"name": "B", "tagType": "AtomicTag", "dataType": "Int4", "valueSource": "memory"},
]


def _write(d: str, name: str, payload) -> Path:
    p = Path(d) / name
    p.write_text(json.dumps(payload))
    return p


class TestTagImportHelp(unittest.TestCase):
    """(d) `ign tag --help` and `tag import --help` list the command."""

    def test_tag_help_lists_import(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("import", result.output)

    def test_import_help_shows_options(self) -> None:
        from ignition_gen_sdk.cli import app

        result = _runner().invoke(app, ["tag", "import", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("--file", result.output)
        self.assertIn("--provider", result.output)
        self.assertIn("--collision-policy", result.output)
        self.assertIn("--dry-run", result.output)


class TestTagImportSuccess(unittest.TestCase):
    """(a) valid file → success path + correct URL / params on the POST."""

    def test_import_posts_body_with_correct_url_and_params(self) -> None:
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "tags.json", _IMPORT_BODY)

            with patch("ignition_gen_sdk.cli.cmd_tag.IgnitionAPIClient") as client_cls, \
                    patch("ignition_gen_sdk.cli.cmd_tag.Settings") as settings_cls, \
                    patch("ignition_gen_sdk.cli.cmd_tag.ScanClient") as scan_cls:
                settings_cls.return_value = MagicMock()
                client_inst = MagicMock()
                resp = MagicMock()
                resp.text = '{"successCount": 1, "failureCount": 0}'
                resp.json.return_value = {"successCount": 1, "failureCount": 0}
                client_inst.request.return_value = resp
                client_cls.return_value = client_inst
                # ScanClient used as a context manager.
                scan_cls.return_value.__enter__.return_value = MagicMock()
                scan_cls.return_value.__exit__.return_value = False

                result = _runner().invoke(
                    app,
                    [
                        "tag", "import",
                        "--file", str(p),
                        "--provider", "default",
                        "--path", "Loop/G1",
                        "--collision-policy", "Overwrite",
                        "--confirm",
                    ],
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        # Exactly one POST through the shared client.
        client_inst.request.assert_called_once()
        method, url = client_inst.request.call_args.args[0], client_inst.request.call_args.args[1]
        self.assertEqual(method, "POST")
        self.assertTrue(url.startswith("/data/api/v1/tags/import?"), msg=url)
        self.assertIn("provider=default", url)
        self.assertIn("path=Loop", url)  # urlencoded slash → Loop%2FG1
        self.assertIn("type=json", url)
        self.assertIn("collisionPolicy=Overwrite", url)
        # Body posted verbatim (NOT re-wrapped).
        posted_body = client_inst.request.call_args.kwargs["json"]
        self.assertEqual(posted_body, _IMPORT_BODY)
        # successCount / failureCount surfaced.
        self.assertIn("successCount=1", result.stdout)
        self.assertIn("failureCount=0", result.stdout)

    def test_import_accepts_bare_list_body(self) -> None:
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "tags.json", _BARE_LIST)

            with patch("ignition_gen_sdk.cli.cmd_tag.IgnitionAPIClient") as client_cls, \
                    patch("ignition_gen_sdk.cli.cmd_tag.Settings") as settings_cls, \
                    patch("ignition_gen_sdk.cli.cmd_tag.ScanClient") as scan_cls:
                settings_cls.return_value = MagicMock()
                client_inst = MagicMock()
                resp = MagicMock()
                resp.text = '{"successCount": 2, "failureCount": 0}'
                resp.json.return_value = {"successCount": 2, "failureCount": 0}
                client_inst.request.return_value = resp
                client_cls.return_value = client_inst
                scan_cls.return_value.__enter__.return_value = MagicMock()
                scan_cls.return_value.__exit__.return_value = False

                result = _runner().invoke(
                    app, ["tag", "import", "--file", str(p), "--no-scan", "--confirm"]
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        posted_body = client_inst.request.call_args.kwargs["json"]
        self.assertEqual(posted_body, {"tags": _BARE_LIST})  # bare lists are wrapped: the gateway rejects arrays
        self.assertIn("successCount=2", result.stdout)


class TestTagImportMissingFile(unittest.TestCase):
    """(b) missing --file → exit 1 (Typer flags the required option)."""

    def test_missing_file_exits_1(self) -> None:
        from ignition_gen_sdk.cli import app

        # No HTTP patch needed — the required-option error fires before any
        # client construction. Patch IgnitionAPIClient to PROVE it is never
        # constructed when --file is absent.
        with patch("ignition_gen_sdk.cli.cmd_tag.IgnitionAPIClient") as client_cls:
            result = _runner().invoke(app, ["tag", "import"])
        self.assertEqual(result.exit_code, 1, msg=result.output)
        client_cls.assert_not_called()


class TestTagImportDryRun(unittest.TestCase):
    """(c) --dry-run makes NO HTTP call; prints URL + body summary."""

    def test_dry_run_makes_no_http_call(self) -> None:
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "tags.json", _IMPORT_BODY)

            with patch("ignition_gen_sdk.cli.cmd_tag.IgnitionAPIClient") as client_cls, \
                    patch("ignition_gen_sdk.cli.cmd_tag.ScanClient") as scan_cls:
                result = _runner().invoke(
                    app,
                    [
                        "tag", "import",
                        "--file", str(p),
                        "--provider", "default",
                        "--path", "Loop/G1",
                        "--dry-run",
                    ],
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        # No client, no scan — dry-run is pure local rendering.
        client_cls.assert_not_called()
        scan_cls.assert_not_called()
        # URL + body summary printed.
        self.assertIn("/data/api/v1/tags/import?", result.stdout)
        self.assertIn("provider=default", result.stdout)
        self.assertIn("collisionPolicy=Overwrite", result.stdout)
        self.assertIn("tags: 1", result.stdout)


class TestTagImportBadCollisionPolicy(unittest.TestCase):
    """Invalid --collision-policy → exit 1 before any HTTP call."""

    def test_bad_collision_policy_exits_1(self) -> None:
        from ignition_gen_sdk.cli import app

        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "tags.json", _IMPORT_BODY)
            with patch("ignition_gen_sdk.cli.cmd_tag.IgnitionAPIClient") as client_cls:
                result = _runner().invoke(
                    app,
                    ["tag", "import", "--file", str(p),
                     "--collision-policy", "Nope", "--confirm"],
                )
        self.assertEqual(result.exit_code, 1, msg=result.output)
        client_cls.assert_not_called()
        self.assertIn("collision-policy", result.stderr)


if __name__ == "__main__":
    unittest.main()
