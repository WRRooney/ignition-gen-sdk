"""Tests for `ign tag set-udt-type-prop` — surgical one-prop edits on the
TYPE NODE (the flat ``meta_*`` layer that UDT-driven views read).

No network: Settings points at a tempdir and the verb runs with --no-scan.
The load-bearing assertion is that ONLY the named type's named prop moves —
sibling types, members and member order must survive untouched.
"""
from __future__ import annotations

from conftest import GATEWAY_URL

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


_TYPES = [
    {
        "meta_order": 20.0,
        "meta_view": "",
        "name": "_Field",
        "tagType": "UdtType",
        "typeId": "_Global",
        "tags": [
            {"name": "Enabled", "tagType": "AtomicTag", "dataType": "Boolean",
             "valueSource": "memory", "value": True},
            {"name": "Value", "tagType": "AtomicTag", "dataType": "Float4",
             "valueSource": "opc"},
        ],
    },
    {
        "meta_view": "Field/Input/TextField",
        "name": "TextField",
        "tagType": "UdtType",
        "typeId": "Field/_Field",
        "tags": [{"name": "Value", "tagType": "AtomicTag", "dataType": "String"}],
    },
]


def _settings_for(root: Path):
    from ignition_gen_sdk.config import Settings

    return Settings(
        ignition_api_key="test:test",
        ignition_base_url=GATEWAY_URL,
        ignition_data_root=str(root),
    )


def _seed(root: Path) -> Path:
    dest = (root / "config/resources/core/ignition/tag-type-definition"
            / "default" / "Field")
    dest.mkdir(parents=True)
    (dest / "udts.json").write_text(json.dumps(_TYPES, indent=2))
    return dest


def _run(root: Path, *args: str):
    from ignition_gen_sdk.cli import app
    import ignition_gen_sdk.cli.cmd_tag as cmd_tag

    with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)):
        return _runner().invoke(app, ["tag", "set-udt-type-prop", *args])


class TestSetUdtTypeProp(unittest.TestCase):
    def test_help_lists_verb(self):
        from ignition_gen_sdk.cli import app

        r = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(r.exit_code, 0, msg=r.output)
        self.assertIn("set-udt-type-prop", r.output)

    def test_sets_prop_on_named_type_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            r = _run(root, "--provider", "default", "--path", "Field",
                     "--type", "_Field", "--prop", "meta_hideOnDisabled",
                     "--value", "false", "--no-scan")
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            out = json.loads((dest / "udts.json").read_text())

        types = {t["name"]: t for t in out}
        self.assertIs(types["_Field"]["meta_hideOnDisabled"], False)
        # Sibling type untouched; no prop smuggled onto it or onto a member.
        self.assertNotIn("meta_hideOnDisabled", types["TextField"])
        self.assertNotIn("meta_hideOnDisabled", types["_Field"]["tags"][0])
        # Siblings, order, members preserved.
        self.assertEqual([t["name"] for t in out], ["_Field", "TextField"])
        self.assertEqual([m["name"] for m in types["_Field"]["tags"]], ["Enabled", "Value"])
        self.assertEqual(types["_Field"]["meta_order"], 20.0)

    def test_rerun_is_a_noop_and_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            args = ("--provider", "default", "--path", "Field", "--type", "_Field",
                    "--prop", "meta_hideOnDisabled", "--value", "false", "--no-scan")
            _run(root, *args)
            first = (dest / "udts.json").read_text()
            r = _run(root, *args)
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            self.assertIn("No change", r.stdout)
            self.assertEqual((dest / "udts.json").read_text(), first)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            before = (dest / "udts.json").read_text()
            r = _run(root, "--provider", "default", "--path", "Field", "--type", "_Field",
                     "--prop", "meta_hideOnDisabled", "--value", "true", "--dry-run")
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            self.assertEqual((dest / "udts.json").read_text(), before)
            self.assertIs(json.loads(r.stdout)[0]["meta_hideOnDisabled"], True)

    def test_unknown_type_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _seed(root)
            r = _run(root, "--provider", "default", "--path", "Field", "--type", "Nope",
                     "--prop", "meta_hideOnDisabled", "--value", "true", "--no-scan")
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("no UDT type named", r.stderr)

    def test_missing_file_errors(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run(Path(d), "--provider", "default", "--path", "Nope", "--type", "_Field",
                     "--prop", "meta_hideOnDisabled", "--value", "true", "--no-scan")
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
