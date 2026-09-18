"""ign view replace-text — surgical literal edit inside an existing view.json.

The view-side counterpart to `script replace-text`: reaches tokens the typed
surface does not, such as a message handler's messageType or an event-script
body, without round-tripping the whole view.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.cli import app

VIEW = {
    "custom": {},
    "params": {},
    "props": {},
    "root": {
        "meta": {"name": "root"},
        "type": "ia.container.flex",
        "props": {"style": {"classes": "legacy-alarm-table"}},
        "scripts": {
            "messageHandlers": [
                {
                    "messageType": "legacy-loc-seed-request",
                    "pageScope": True,
                    "script": '\tsystem.perspective.sendMessage("legacy-loc-seed", {}, scope="page")',
                }
            ]
        },
        "children": [
            {"meta": {"name": "Keep"}, "type": "ia.display.label", "props": {"text": "untouched"}},
        ],
    },
}


class TestViewReplaceText(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.view_dir = root / "projects" / "P" / "com.inductiveautomation.perspective" / "views" / "Nav" / "Foot"
        self.view_dir.mkdir(parents=True)
        (root / "projects" / "P" / "project.json").write_text('{"title":"P"}')
        (self.view_dir / "view.json").write_text(json.dumps(VIEW))
        (self.view_dir / "resource.json").write_text(
            '{"scope":"A","version":1,"restricted":false,"overridable":true,'
            '"files":["view.json"],"attributes":{},"documentation":"KEEP ME"}'
        )
        self._mp = pytest.MonkeyPatch()
        self._mp.setenv("IGNITION_DATA_DIR", self._tmp.name)

    def tearDown(self):
        self._mp.undo()
        self._tmp.cleanup()

    def _run(self, *args):
        return CliRunner().invoke(
            app,
            ["view", "replace-text", "--project", "P", "--view-path", "Nav/Foot", "--no-scan", *args],
        )

    def _text(self):
        return (self.view_dir / "view.json").read_text()

    def test_renames_message_type_in_handler_and_body(self):
        """A prefix rename covers the -request variant and the send in one pass."""
        r = self._run("--old", "legacy-loc-seed", "--new", "location-seed")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        text = self._text()
        self.assertNotIn("legacy-loc-seed", text)
        handler = json.loads(text)["root"]["scripts"]["messageHandlers"][0]
        self.assertEqual(handler["messageType"], "location-seed-request")
        # Assert on the PARSED body: on disk the inner quotes are escaped (\") and
        # `=` is written =, so a raw substring check tests the serializer, not
        # the rename. Callers hit the same trap — see the --old help text.
        self.assertIn('sendMessage("location-seed"', handler["script"])

    def test_renames_a_style_class(self):
        r = self._run("--old", "legacy-alarm-table", "--new", "alarm-table")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        root = json.loads(self._text())["root"]
        self.assertEqual(root["props"]["style"]["classes"], "alarm-table")

    def test_untouched_content_and_resource_survive(self):
        self.assertEqual(self._run("--old", "legacy-alarm-table", "--new", "alarm-table").exit_code, 0)
        root = json.loads(self._text())["root"]
        self.assertEqual(root["children"][0]["props"]["text"], "untouched")
        self.assertIn("KEEP ME", (self.view_dir / "resource.json").read_text())

    def test_expect_mismatch_refuses(self):
        self.assertEqual(
            self._run("--old", "legacy-alarm-table", "--new", "alarm-table", "--expect", "3").exit_code, 1
        )
        self.assertIn("legacy-alarm-table", self._text())  # no write

    def test_expect_match_allows(self):
        r = self._run("--old", "legacy-alarm-table", "--new", "alarm-table", "--expect", "1")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertNotIn("legacy-alarm-table", self._text())

    def test_missing_old_is_an_error_not_a_silent_noop(self):
        self.assertEqual(self._run("--old", "nosuchtoken", "--new", "x").exit_code, 1)
        self.assertEqual(json.loads(self._text()), VIEW)

    def test_replacement_breaking_json_is_refused(self):
        # Kill a quote -> invalid JSON, refused before any disk write.
        self.assertEqual(self._run("--old", '"root"', "--new", '"root').exit_code, 1)
        self.assertEqual(json.loads(self._text()), VIEW)

    def test_replacement_breaking_the_model_is_refused(self):
        # root.type is required by the Component model; blank it out.
        self.assertEqual(self._run("--old", '"type"', "--new", '"typo"').exit_code, 1)
        self.assertEqual(json.loads(self._text()), VIEW)

    def test_dry_run_reports_without_writing(self):
        r = self._run("--old", "legacy-alarm-table", "--new", "alarm-table", "--dry-run")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertIn("1 occurrence", r.stdout)
        self.assertEqual(json.loads(self._text()), VIEW)

    def test_noop_and_empty_args_rejected(self):
        self.assertEqual(self._run("--old", "x", "--new", "x").exit_code, 1)
        self.assertEqual(self._run("--old", "", "--new", "y").exit_code, 1)
        self.assertEqual(json.loads(self._text()), VIEW)
