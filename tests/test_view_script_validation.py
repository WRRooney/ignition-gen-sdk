"""A view whose embedded Python does not parse must not be written.

Perspective stores binding transforms, event handlers, message handlers and
custom methods as the BODY of a function it wraps at runtime. A broken one is
therefore not a load error: the view saves, the page renders, and the binding
simply never produces a value. The operator sees an empty list or a default,
and only the gateway log knows why.

That is exactly how a comment line that lost its leading '#' shipped a user
management page reporting "No users match." against a populated user source --
and did it convincingly enough to pass a hand-written check for the data leak
the very same edit was meant to fix.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _payload(code):
    return {"propConfig": {"custom.rows": {"binding": {"transforms": [
        {"code": code, "type": "script"}]}}}}


class TestValidateViewScripts(unittest.TestCase):
    def test_indented_body_is_accepted(self):
        from ignition_gen_sdk.backends.project_disk import validate_view_scripts

        validate_view_scripts(_payload("\tif not value.ok:\n\t\treturn []\n\treturn [1]"))

    def test_column0_comment_above_indented_body_is_accepted(self):
        # Comment lines are invisible to indentation rules; a col-0 comment
        # above a tab-indented body must still get the def wrapper
        # (real case: ExcelReports Excel Query onActionPerformed).
        from ignition_gen_sdk.backends.project_disk import validate_view_scripts

        validate_view_scripts(_payload(
            "#\tfor k, v in pairs:\n#\t\tuse(k, v)\n\tx = 1\n\ty = x"))

    def test_unindented_body_is_accepted(self):
        from ignition_gen_sdk.backends.project_disk import validate_view_scripts

        validate_view_scripts({"events": {"dom": {"onClick": {
            "config": {"script": "x = 1"}}}}})

    def test_a_comment_missing_its_hash_is_rejected(self):
        from ignition_gen_sdk.backends.project_disk import (
            validate_view_scripts, ViewScriptError)

        with self.assertRaises(ViewScriptError) as ctx:
            validate_view_scripts(_payload(
                "\t# first line is a comment\n"
                "\tsecond line lost its hash\n"
                "\treturn []"))
        self.assertIn("custom.rows", str(ctx.exception))

    def test_every_script_key_is_checked(self):
        from ignition_gen_sdk.backends.project_disk import (
            validate_view_scripts, ViewScriptError)

        for payload in (
            # NB "this is not python" would PARSE (it reads as `this is (not
            # python)`), so the example has to be genuinely malformed. A syntax
            # check catches broken grammar, not nonsense that happens to be
            # well-formed -- which is the honest limit of this guard.
            {"events": {"component": {"onActionPerformed": {
                "config": {"script": "\tif :\n\t\tpass"}}}}},
            {"scripts": {"messageHandlers": [
                {"messageType": "x", "script": "\tdef ("}]}},
            {"root": {"children": [{"propConfig": {"props.text": {"binding": {
                "transforms": [{"code": "\treturn (", "type": "script"}]}}}}]}},
        ):
            with self.subTest(payload=str(payload)[:40]):
                with self.assertRaises(ViewScriptError):
                    validate_view_scripts(payload)

    def test_blank_scripts_are_ignored(self):
        from ignition_gen_sdk.backends.project_disk import validate_view_scripts

        validate_view_scripts(_payload("   \n\t\n"))

    def test_write_view_refuses_and_writes_nothing(self):
        from ignition_gen_sdk.backends.project_disk import (
            ProjectDiskBackend, ViewScriptError)
        from ignition_gen_sdk.config import Settings
        from ignition_gen_sdk.models.views.view import View

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "projects" / "Demo"
            proj.mkdir(parents=True)
            (proj / "project.json").write_text('{"title":"Demo"}')
            view = View.model_validate({
                "custom": {}, "params": {},
                "propConfig": {"custom.rows": {"binding": {
                    "config": {"expression": "1"},
                    "transforms": [{"code": "\toops not python", "type": "script"}],
                    "type": "expr"}}},
                "props": {}, "root": {"meta": {"name": "root"},
                                      "type": "ia.container.flex"},
            })
            with patch.dict(os.environ,
                            {"IGNITION_API_TOKEN": "test:dummy",
                             "IGNITION_DATA_DIR": str(root)}, clear=False):
                backend = ProjectDiskBackend(Settings())  # type: ignore[call-arg]
                with self.assertRaises(ViewScriptError):
                    backend.write_view("Demo", "Bad/View", view)
            self.assertFalse(
                (proj / "com.inductiveautomation.perspective" / "views" / "Bad"
                 / "View" / "view.json").exists(),
                "a rejected view must leave nothing behind")


if __name__ == "__main__":
    unittest.main()
