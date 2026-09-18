"""Tests for the NEW-resource registration NOTE on `page mount` +
`session-props declare`.

A running gateway was once believed NOT to register a newly-ADDED resource from
a project scan (it only re-reads edits to already-registered ones). So these
write commands now emit a stderr NOTE when they CREATE a resource (and stay
quiet when they merely merge into an existing one), so a user isn't misled into
thinking a scan made the new resource live.

Mirrors tests/test_new_resource_note.py.

Test IDs:
  - test_page_mount_new_emits_note
  - test_page_mount_existing_no_note
  - test_session_props_declare_new_emits_note
  - test_session_props_declare_existing_no_note
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


def _make_project(root: Path, name: str = "TestProj") -> None:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')


def _invoke(root: Path, args: list[str]):
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)}, clear=False):
        from ignition_gen_sdk.cli import app
        return _runner().invoke(app, args)


_RELOAD_PHRASES = ("does NOT register", "reload/restart", "NEW page-config",
                   "NEW session-props")


class TestNoReloadNote(unittest.TestCase):
    """Project resources register on a project scan —
    no reload gate (gateway-owner-corrected). `page mount` + `session-props
    declare` must NOT emit a 'needs reload' note."""

    def test_page_mount_emits_no_reload_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            res = _invoke(root, ["page", "mount", "--project", "TestProj",
                                 "--url", "/", "--view-path", "Demo/Hello", "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            for p in _RELOAD_PHRASES:
                self.assertNotIn(p, res.output)

    def test_session_props_declare_emits_no_reload_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root)
            pf = root / "props.json"
            pf.write_text(json.dumps({"app": {"selectedView": ""}}))
            res = _invoke(root, ["session-props", "declare", "--project", "TestProj",
                                 "--file", str(pf), "--no-scan"])
            self.assertEqual(res.exit_code, 0, res.output)
            for p in _RELOAD_PHRASES:
                self.assertNotIn(p, res.output)


if __name__ == "__main__":
    unittest.main()
