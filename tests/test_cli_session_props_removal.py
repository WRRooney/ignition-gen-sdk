"""Tests for `ign session-props undeclare` and `session-props delete`.

Both exist because of a property of Perspective that bit this project twice:

* A custom SESSION property can carry a BINDING, and a session binding runs in
  every open session for as long as the project declares it -- whether or not
  anything reads the value. `undeclare` has to take the propConfig entries with
  the property, or the binding stays declared and keeps polling.
* Session-props (like page-config) inherit per RESOURCE, not per property. A
  child project holding any session-props of its own overrides the parent's
  completely, so a prop declared only on the parent is invisible in the child.
  `delete` removes the child's resource so it inherits again.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _runner():
    from typer.testing import CliRunner

    return CliRunner()


def _env(root: Path):
    return patch.dict(
        os.environ,
        {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
        clear=False,
    )


def _make_project(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"%s"}' % name)
    return proj


def _seed(root: Path, project: str):
    """A project with two custom props, one of them carrying a binding."""
    with _env(root):
        from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
        from ignition_gen_sdk.config import Settings
        from ignition_gen_sdk.models.session_props import SessionProps

        backend = ProjectDiskBackend(Settings())  # type: ignore[call-arg]
        sp = SessionProps(
            custom={"DMC": {"area": "", "rangeHours": 8}, "nav": {"path": ""}},
            propConfig={
                "custom.DMC.area": {"persistent": True},
                "custom.DMC.kpis": {"binding": {
                    "config": {"expression": "toStr(now(30000))"},
                    "type": "expr"}},
                "custom.nav.path": {"persistent": True},
            },
        )
        return backend.write_session_props(project, sp)


def _invoke(root: Path, args: list[str]):
    with _env(root):
        from ignition_gen_sdk.cli import app

        return _runner().invoke(app, args)


def _props(root: Path, project: str) -> dict:
    return json.loads(
        (root / "projects" / project / "com.inductiveautomation.perspective"
         / "session-props" / "props.json").read_text()
    )


class TestUndeclare(unittest.TestCase):
    def test_removes_the_prop_and_its_bindings_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "P")
            _seed(root, "P")
            res = _invoke(root, ["session-props", "undeclare", "--project", "P",
                                 "--name", "DMC", "--no-scan"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            props = _props(root, "P")
            self.assertEqual(sorted(props["custom"]), ["nav"])
            # The binding must go with the property it was declared on.
            self.assertEqual(sorted(props["propConfig"]), ["custom.nav.path"])

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "P")
            _seed(root, "P")
            res = _invoke(root, ["session-props", "undeclare", "--project", "P",
                                 "--name", "DMC", "--dry-run"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertIn("custom.DMC.kpis", res.output)
            self.assertEqual(sorted(_props(root, "P")["custom"]), ["DMC", "nav"])

    def test_unknown_prop_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "P")
            _seed(root, "P")
            res = _invoke(root, ["session-props", "undeclare", "--project", "P",
                                 "--name", "nope", "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertEqual(sorted(_props(root, "P")["custom"]), ["DMC", "nav"])


class TestDelete(unittest.TestCase):
    def test_removes_the_whole_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Child")
            dest = _seed(root, "Child")
            res = _invoke(root, ["session-props", "delete", "--project", "Child",
                                 "--confirm", "--no-scan"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertFalse(Path(dest).exists())

    def test_confirm_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Child")
            dest = _seed(root, "Child")
            res = _invoke(root, ["session-props", "delete", "--project", "Child",
                                 "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertIn("undeclare", res.output)
            self.assertTrue(Path(dest).exists())

    def test_missing_resource_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Bare")
            res = _invoke(root, ["session-props", "delete", "--project", "Bare",
                                 "--confirm", "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertIn("inherits", res.output)


class TestDeclarePropConfig(unittest.TestCase):
    """`declare --prop-config` is the only way to put a BINDING or an onChange
    on a session property -- including a BUILT-IN one like props.theme, which
    is not a custom prop and so cannot be reached through --file at all."""

    def _config(self, root: Path, payload: dict) -> Path:
        path = root / "pc.json"
        path.write_text(json.dumps(payload))
        return path

    def test_binds_a_builtin_prop_and_merges_with_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            _seed(root, "Demo")
            pc = self._config(root, {"props.theme": {"binding": {
                "config": {"expression": "'dark-cool'"}, "type": "expr"}}})
            res = _invoke(root, ["session-props", "declare", "--project", "Demo",
                                 "--prop-config", str(pc), "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            config = _props(root, "Demo")["propConfig"]
            self.assertIn("props.theme", config)
            # the seeded entries survive; this is a merge, not a replace
            self.assertIn("custom.DMC.kpis", config)
            self.assertIn("custom.nav.path", config)

    def test_declares_custom_props_and_their_config_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            props = root / "p.json"
            props.write_text(json.dumps({"user": {"id": ""}}))
            pc = self._config(root, {"custom.user.id": {
                "onChange": {"enabled": True, "script": "\tpass"}}})
            res = _invoke(root, ["session-props", "declare", "--project", "Demo",
                                 "--file", str(props), "--prop-config", str(pc),
                                 "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            written = _props(root, "Demo")
            self.assertEqual(written["custom"]["user"], {"id": ""})
            self.assertTrue(written["propConfig"]["custom.user.id"]["onChange"]["enabled"])

    def test_neither_option_is_an_error_not_a_silent_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            res = _invoke(root, ["session-props", "declare", "--project", "Demo",
                                 "--no-scan"])
            self.assertEqual(res.exit_code, 1)
            self.assertIn("nothing to declare", res.output)


if __name__ == "__main__":
    unittest.main()
