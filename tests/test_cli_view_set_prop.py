"""Tests for `ign view set-prop` — edit one view-level custom/params prop in place."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.cli import app

VIEW = {
    "custom": {"query": "", "selected": "[default]System"},
    "params": {"popup": False},
    "propConfig": {
        "custom.query": {"persistent": True},
        "custom.selected": {"persistent": True},
        "params.popup": {"paramDirection": "input", "persistent": True},
    },
    "props": {},
    "root": {
        "meta": {"name": "root"},
        "type": "ia.container.flex",
        "propConfig": {
            "props.style.pointerEvents": {
                "binding": {"config": {"expression": "if({view.custom.gone}, 1, 0)"}, "type": "expr"}
            },
            "props.style.opacity": {"binding": {"config": {"expression": "1"}, "type": "expr"},
                                    "persistent": True},
        },
        "children": [
            {
                "meta": {"name": "Body"},
                "type": "ia.container.flex",
                "props": {"style": {"classes": "old"}},
                "children": [
                    {"meta": {"name": "Label"}, "type": "ia.display.label",
                     "props": {"text": "hi", "currentBreakpoint": "large"}},
                ],
            },
        ],
    },
}


class TestSetProp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.view_dir = root / "projects" / "P" / "com.inductiveautomation.perspective" / "views" / "Nav" / "Menu"
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
            app, ["view", "set-prop", "--project", "P", "--view-path", "Nav/Menu", "--no-scan", *args]
        )

    def _view(self):
        return json.loads((self.view_dir / "view.json").read_text())

    def test_no_persistent_drops_seed_and_sets_flag(self):
        r = self._run("--prop", "custom.selected", "--no-persistent")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        v = self._view()
        self.assertNotIn("selected", v["custom"])
        self.assertEqual(v["propConfig"]["custom.selected"], {"persistent": False})
        self.assertEqual(v["custom"]["query"], "")  # siblings untouched
        self.assertIn("KEEP ME", (self.view_dir / "resource.json").read_text())

    def test_value_parses_json_else_string(self):
        self.assertEqual(self._run("--prop", "custom.selected", "--value", '""').exit_code, 0)
        self.assertEqual(self._view()["custom"]["selected"], "")
        self.assertEqual(self._run("--prop", "params.popup", "--value", "true").exit_code, 0)
        self.assertIs(self._view()["params"]["popup"], True)
        self.assertEqual(self._run("--prop", "custom.selected", "--value", "[default]X").exit_code, 0)
        self.assertEqual(self._view()["custom"]["selected"], "[default]X")

    def test_nested_prop_and_persistent_true(self):
        r = self._run("--prop", "custom.nav.path", "--value", '"a/b"', "--persistent")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        v = self._view()
        self.assertEqual(v["custom"]["nav"], {"path": "a/b"})
        self.assertEqual(v["propConfig"]["custom.nav.path"], {"persistent": True})

    def test_dry_run_does_not_write(self):
        r = self._run("--prop", "custom.selected", "--unset", "--dry-run")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertNotIn("selected", json.loads(r.stdout)["custom"])
        self.assertEqual(self._view()["custom"]["selected"], "[default]System")

    def test_rejects_bad_prop_and_no_op(self):
        self.assertEqual(self._run("--prop", "props.text", "--value", "x").exit_code, 1)
        self.assertEqual(self._run("--prop", "custom.selected").exit_code, 1)
        self.assertEqual(self._run("--prop", "custom.selected", "--value", "x", "--unset").exit_code, 1)
        self.assertEqual(self._view(), VIEW)

    # --- --component -------------------------------------------------------

    def _root(self):
        return self._view()["root"]

    def test_component_sets_nested_prop(self):
        r = self._run("--component", "root/Body/Label", "--prop", "props.text", "--value", "bye")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        label = self._root()["children"][0]["children"][0]
        self.assertEqual(label["props"]["text"], "bye")
        # sibling component untouched
        self.assertEqual(self._root()["children"][0]["props"]["style"]["classes"], "old")

    def test_component_unset_drops_leaked_editor_state(self):
        r = self._run("--component", "root/Body/Label", "--prop", "props.currentBreakpoint", "--unset")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        label = self._root()["children"][0]["children"][0]
        self.assertNotIn("currentBreakpoint", label["props"])
        self.assertEqual(label["props"]["text"], "hi")

    def test_component_root_targets_root_itself(self):
        r = self._run("--component", "root", "--prop", "props.style.classes", "--value", "page")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertEqual(self._root()["props"]["style"]["classes"], "page")

    def test_unset_binding_removes_entry_and_keeps_siblings(self):
        r = self._run("--component", "root", "--prop", "props.style.pointerEvents",
                      "--unset-binding", "--value", '"none"')
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        root = self._root()
        self.assertNotIn("props.style.pointerEvents", root["propConfig"])
        self.assertEqual(root["props"]["style"]["pointerEvents"], "none")
        # sibling propConfig entry survives
        self.assertIn("props.style.opacity", root["propConfig"])

    def test_unset_binding_keeps_entry_with_other_flags(self):
        r = self._run("--component", "root", "--prop", "props.style.opacity", "--unset-binding")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        entry = self._root()["propConfig"]["props.style.opacity"]
        self.assertEqual(entry, {"persistent": True})

    def _binding_file(self, payload) -> str:
        p = Path(self._tmp.name) / "binding.json"
        p.write_text(json.dumps(payload))
        return str(p)

    def test_binding_file_adds_view_level_binding(self):
        f = self._binding_file({
            "config": {
                "fallbackDelay": 2.5,
                "mode": "indirect",
                "references": {"tagPath": "{view.params.tagPath}"},
                "tagPath": "{tagPath}.meta_hideOnDisabled",
            },
            "type": "tag",
        })
        r = self._run("--prop", "custom.query", "--binding-file", f, "--persistent")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        entry = self._view()["propConfig"]["custom.query"]
        self.assertEqual(entry["binding"]["type"], "tag")
        self.assertEqual(entry["binding"]["config"]["tagPath"], "{tagPath}.meta_hideOnDisabled")
        self.assertIs(entry["persistent"], True)
        # untouched siblings
        self.assertIn("custom.selected", self._view()["propConfig"])

    def test_binding_file_replaces_component_binding(self):
        f = self._binding_file(
            {"config": {"expression": 'if({view.custom.show}, "A", "")'}, "type": "expr"}
        )
        r = self._run("--component", "root", "--prop", "props.style.pointerEvents",
                      "--binding-file", f)
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        entry = self._root()["propConfig"]["props.style.pointerEvents"]
        self.assertEqual(entry["binding"]["config"]["expression"],
                         'if({view.custom.show}, "A", "")')

    def test_binding_file_errors_are_no_ops(self):
        bad = self._binding_file({"config": {"expression": "1"}})  # no "type"
        self.assertEqual(self._run("--prop", "custom.query", "--binding-file", bad).exit_code, 1)
        missing = str(Path(self._tmp.name) / "nope.json")
        self.assertEqual(self._run("--prop", "custom.query", "--binding-file", missing).exit_code, 1)
        ok = self._binding_file({"config": {"expression": "1"}, "type": "expr"})
        self.assertEqual(
            self._run("--component", "root", "--prop", "props.style.opacity",
                      "--binding-file", ok, "--unset-binding").exit_code, 1)
        self.assertEqual(self._view(), VIEW)

    def test_component_errors_are_no_ops(self):
        # unknown child, bad start segment, non-component prop head, missing binding
        self.assertEqual(self._run("--component", "root/Nope", "--prop", "props.text",
                                   "--value", "x").exit_code, 1)
        self.assertEqual(self._run("--component", "Body", "--prop", "props.text",
                                   "--value", "x").exit_code, 1)
        self.assertEqual(self._run("--component", "root", "--prop", "params.popup",
                                   "--value", "x").exit_code, 1)
        self.assertEqual(self._run("--component", "root/Body", "--prop", "props.style.classes",
                                   "--unset-binding").exit_code, 1)
        self.assertEqual(self._view(), VIEW)

    def test_binding_only_call_does_not_materialize_empty_props(self):
        """A propConfig-only edit must not leave `props: {}` — a Perspective default."""
        f = self._binding_file({"config": {"expression": "1"}, "type": "expr"})
        r = self._run("--component", "root/Body/Label", "--prop", "props.style.color",
                      "--binding-file", f)
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        label = self._root()["children"][0]["children"][0]
        self.assertIn("props.style.color", label["propConfig"])
        # props existed already (text/currentBreakpoint) and must be untouched
        self.assertEqual(label["props"]["text"], "hi")
        self.assertNotIn("style", label["props"])

    def test_unset_binding_only_leaves_no_empty_container(self):
        r = self._run("--component", "root", "--prop", "props.style.pointerEvents", "--unset-binding")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        root = self._root()
        self.assertNotIn("props.style.pointerEvents", root["propConfig"])
        self.assertNotIn("props", root)  # root had no props dict; none invented
