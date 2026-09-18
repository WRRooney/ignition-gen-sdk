"""ign script replace-text — surgical literal edit inside an existing code.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.cli import app

CODE = '\n'.join([
    "def skeletonPid(width, height):",
    '\treturn {"style": {"clases": "page-pid", "width": width}}',
    "",
    "def skeletonPage():",
    '\treturn {"style": {"classes": "page"}}',
    "",
])


class TestScriptReplaceText(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.pkg = root / "projects" / "P" / "ignition" / "script-python" / "library" / "navbuilder"
        self.pkg.mkdir(parents=True)
        (root / "projects" / "P" / "project.json").write_text('{"title":"P"}')
        (self.pkg / "code.py").write_text(CODE)
        (self.pkg / "resource.json").write_text(json.dumps({"scope": "G", "version": 1}))
        self._mp = pytest.MonkeyPatch()
        self._mp.setenv("IGNITION_DATA_DIR", self._tmp.name)

    def tearDown(self):
        self._mp.undo()
        self._tmp.cleanup()

    def _run(self, *args):
        return CliRunner().invoke(
            app,
            ["script", "replace-text", "--project", "P",
             "--script-path", "library/navbuilder", "--no-scan", *args],
        )

    def _code(self):
        return (self.pkg / "code.py").read_text()

    def test_replaces_and_leaves_the_rest_alone(self):
        r = self._run("--old", '"clases"', "--new", '"classes"')
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        code = self._code()
        self.assertNotIn("clases", code)
        self.assertIn('"classes": "page-pid"', code)
        self.assertIn('"classes": "page"', code)  # untouched sibling

    def test_expect_mismatch_refuses(self):
        self.assertEqual(self._run("--old", '"clases"', "--new", '"classes"', "--expect", "2").exit_code, 1)
        self.assertIn("clases", self._code())  # no write

    def test_expect_match_allows(self):
        r = self._run("--old", '"clases"', "--new", '"classes"', "--expect", "1")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertNotIn("clases", self._code())

    def test_missing_old_is_an_error_not_a_silent_noop(self):
        self.assertEqual(self._run("--old", "nosuchtext", "--new", "x").exit_code, 1)
        self.assertEqual(self._code(), CODE)

    def test_rejects_replacement_that_breaks_syntax(self):
        # Kill the colon on the def line -> SyntaxError, refused before any write.
        self.assertEqual(
            self._run("--old", "def skeletonPage():", "--new", "def skeletonPage(").exit_code, 1
        )
        self.assertEqual(self._code(), CODE)

    def test_rejects_space_indent_replacement(self):
        self.assertEqual(self._run("--old", "\treturn", "--new", "    return").exit_code, 1)
        self.assertEqual(self._code(), CODE)

    def test_dry_run_reports_without_writing(self):
        r = self._run("--old", '"clases"', "--new", '"classes"', "--dry-run")
        self.assertEqual(r.exit_code, 0, msg=r.stdout + (r.stderr or ""))
        self.assertIn("1 occurrence", r.stdout)
        self.assertEqual(self._code(), CODE)

    def test_noop_and_empty_args_rejected(self):
        self.assertEqual(self._run("--old", "x", "--new", "x").exit_code, 1)
        self.assertEqual(self._run("--old", "", "--new", "y").exit_code, 1)
        self.assertEqual(self._code(), CODE)
