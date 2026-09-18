"""Tests for the NEW-resource registration NOTE on `script write` + `view write`.

A running gateway was once believed NOT to register a newly-ADDED resource from a
project scan (it only re-reads edits to already-registered ones) — a brand-new
view renders "View Not Found"; a new library module is undefined. So the write
commands now emit a stderr NOTE when they CREATE a resource (and stay quiet when
they merely edit an existing one), so a user isn't misled into thinking a scan
made the new resource live.

Test IDs:
  - test_script_write_new_emits_note
  - test_script_write_existing_no_note
  - test_view_write_new_emits_note
  - test_view_write_existing_no_note
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


def _make_project(root: Path, name: str = "TestProj") -> None:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')


def _invoke(root: Path, args: list[str]):
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)}, clear=False):
        from ignition_gen_sdk.cli import app
        return _runner().invoke(app, args)


class TestScriptWriteNoReloadNote(unittest.TestCase):
    """Library code.py loads on a project scan (no
    reload gate — gateway-owner-corrected). `script write` must NOT emit a
    'NEW module needs reload' note. (If a module misbehaves, check the gateway
    logs — GET /data/api/v1/logs — for a real init/runtime error.)"""

    def test_script_write_emits_no_reload_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            code = root / "mod.py"
            code.write_text("def f():\n\treturn 1\n")
            res = _invoke(root, ["script", "write", "--project", "TestProj",
                                 "--script-path", "pkg/newmod", "--file", str(code), "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            for phrase in ("NEW script module", "does NOT register", "reload/restart"):
                self.assertNotIn(phrase, res.output)


class TestViewWriteNoRegistrationNote(unittest.TestCase):
    """Views register on a project scan (proven live),
    so `view write` must NOT emit a 'NEW view needs reload' note. The reload
    caveat applies only to project-LIBRARY code.py (see the script-write tests)."""

    def test_view_write_new_emits_no_registration_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            res = _invoke(root, ["view", "write", "--project", "TestProj",
                                 "--view-path", "Demo/Hello", "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertNotIn("NEW view", res.output)
            self.assertNotIn("View Not Found", res.output)


if __name__ == "__main__":
    unittest.main()
