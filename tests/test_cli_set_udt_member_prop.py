"""Tests for `ign tag set-udt-member-prop` — surgical one-prop UDT edits.

No network: Settings points at a tempdir and the verb runs with --no-scan.
The load-bearing assertion is that ONLY the targeted property moves: siblings,
member order, member kinds and non-matching members must survive untouched.
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


# Two types; one has a Folder member so the walk has to recurse. Mixed
# valueSource so --where has something to skip.
_TYPES = [
    {
        "name": "Motor",
        "tagType": "UdtType",
        "tags": [
            {"name": "Running", "tagType": "AtomicTag", "dataType": "Boolean",
             "valueSource": "opc"},
            {"name": "Label", "tagType": "AtomicTag", "dataType": "String",
             "valueSource": "memory", "value": "M1"},
            {"name": "Nested", "tagType": "Folder", "tags": [
                {"name": "Speed", "tagType": "AtomicTag", "dataType": "Float4",
                 "valueSource": "opc"},
            ]},
        ],
    },
    {
        "name": "Sibling",
        "tagType": "UdtType",
        "tags": [
            {"name": "Value", "tagType": "AtomicTag", "dataType": "Float8",
             "valueSource": "memory", "value": 0.0},
        ],
    },
]

_SERVER = "Ignition OPC UA Server"


def _settings_for(root: Path):
    from ignition_gen_sdk.config import Settings

    return Settings(
        ignition_api_key="test:test",
        ignition_base_url=GATEWAY_URL,
        ignition_data_root=str(root),
    )


def _seed(root: Path) -> Path:
    dest = (root / "config/resources/core/ignition/tag-type-definition"
            / "default" / "Component")
    dest.mkdir(parents=True)
    (dest / "udts.json").write_text(json.dumps(_TYPES, indent=2))
    return dest


def _run(root: Path, *args: str):
    from ignition_gen_sdk.cli import app
    import ignition_gen_sdk.cli.cmd_tag as cmd_tag

    with mock.patch.object(cmd_tag, "Settings", lambda: _settings_for(root)):
        return _runner().invoke(app, ["tag", "set-udt-member-prop", *args])


class TestSetUdtMemberProp(unittest.TestCase):
    def test_help_lists_verb(self):
        from ignition_gen_sdk.cli import app

        r = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(r.exit_code, 0, msg=r.output)
        self.assertIn("set-udt-member-prop", r.output)

    def test_sets_prop_on_matching_members_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            r = _run(root, "--provider", "default", "--path", "Component",
                     "--prop", "opcServer", "--value", _SERVER,
                     "--where", "valueSource=opc", "--no-scan")
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            out = json.loads((dest / "udts.json").read_text())

        # Both opc members patched — including the one nested in a Folder.
        motor = {t["name"]: t for t in out}["Motor"]
        members = {m["name"]: m for m in motor["tags"]}
        self.assertEqual(members["Running"]["opcServer"], _SERVER)
        self.assertEqual(members["Nested"]["tags"][0]["opcServer"], _SERVER)
        # Non-matching member untouched; no opcServer smuggled in.
        self.assertNotIn("opcServer", members["Label"])
        self.assertEqual(members["Label"]["value"], "M1")
        # Siblings, order and kinds preserved.
        self.assertEqual([t["name"] for t in out], ["Motor", "Sibling"])
        self.assertEqual([m["name"] for m in motor["tags"]],
                         ["Running", "Label", "Nested"])
        self.assertEqual(members["Nested"]["tagType"], "Folder")
        self.assertIn("2 member(s)", r.stdout)

    def test_rerun_is_a_noop_and_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            _run(root, "--provider", "default", "--path", "Component",
                 "--prop", "opcServer", "--value", _SERVER,
                 "--where", "valueSource=opc", "--no-scan")
            first = (dest / "udts.json").read_text()
            r = _run(root, "--provider", "default", "--path", "Component",
                     "--prop", "opcServer", "--value", _SERVER,
                     "--where", "valueSource=opc", "--no-scan")
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            self.assertIn("No change", r.stdout)
            self.assertEqual((dest / "udts.json").read_text(), first)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dest = _seed(root)
            before = (dest / "udts.json").read_text()
            r = _run(root, "--provider", "default", "--path", "Component",
                     "--prop", "opcServer", "--value", _SERVER,
                     "--where", "valueSource=opc", "--dry-run")
            self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
            self.assertEqual((dest / "udts.json").read_text(), before)
            self.assertEqual(json.loads(r.stdout)[0]["tags"][0]["opcServer"], _SERVER)

    def test_missing_file_errors(self):
        with tempfile.TemporaryDirectory() as d:
            r = _run(Path(d), "--provider", "default", "--path", "Nope",
                     "--prop", "opcServer", "--value", _SERVER, "--no-scan")
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("not found", r.stderr)

    def test_malformed_where_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _seed(root)
            r = _run(root, "--provider", "default", "--path", "Component",
                     "--prop", "opcServer", "--value", _SERVER,
                     "--where", "valueSource", "--no-scan")
        self.assertEqual(r.exit_code, 1, msg=r.stdout + r.stderr)
        self.assertIn("KEY=VALUE", r.stderr)


if __name__ == "__main__":
    unittest.main()
