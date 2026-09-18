"""Tests for ProjectDiskBackend.delete_view + ign view delete CLI.

All tests that need a real view on disk write their own temp view first
via backend.write_view so tests are fully self-contained (no dependency on
the generators or any pre-existing view).

Test IDs:
  - test_delete_view_removes_dir
  - test_delete_view_nonexistent_raises
  - test_delete_cmd_dry_run
  - test_delete_cmd_missing_path_exits_1
  - test_delete_cmd_help
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


def _settings_with_root(root: Path):
    """Build a Settings whose ignition_data_root is a temp directory."""
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-delete-tests"}, clear=False):
        from ignition_gen_sdk.config import Settings
        return Settings(ignition_data_root=root)


def _make_temp_project(tmp_root: Path, project: str = "TestProject") -> Path:
    """Scaffold a minimal project directory with project.json so the backend accepts it."""
    proj_dir = tmp_root / "projects" / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "project.json").write_text('{"title":"TestProject","enabled":true}')
    return proj_dir


def _demo_view():
    """Minimal View instance for write_view calls in tests."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    from ignition_gen_sdk.models.views.component import Component
    from ignition_gen_sdk.models.views.meta import Meta
    from ignition_gen_sdk.models.views.positions import FlexChildPosition
    return (ViewBuilder()
            .flex_root(direction="column")
            .add_to_flex(
                Component(
                    type="ia.display.label",
                    meta=Meta(name="Hello"),
                    props={"text": "Hello"},
                ),
                position=FlexChildPosition(basis="56px", shrink=0),
            )
            .build())


class TestDeleteViewRemovesDir(unittest.TestCase):
    """delete_view removes the view directory from disk."""

    def test_delete_view_removes_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_temp_project(root)
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
            backend = ProjectDiskBackend(settings)
            view = _demo_view()
            dest = backend.write_view("TestProject", "Components/test-delete-tmp", view)
            self.assertTrue(dest.is_dir(), "write_view should have created the directory")
            backend.delete_view("TestProject", "Components/test-delete-tmp")
            self.assertFalse(dest.exists(), "delete_view should have removed the directory")


class TestDeleteViewNonexistentRaises(unittest.TestCase):
    """delete_view raises ViewNotFoundError (or FileNotFoundError) on a path that does not exist."""

    def test_delete_view_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_temp_project(root)
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend, ViewNotFoundError
            backend = ProjectDiskBackend(settings)
            with self.assertRaises((ViewNotFoundError, FileNotFoundError)):
                backend.delete_view("TestProject", "Components/does-not-exist")


class TestDeleteCmdDryRun(unittest.TestCase):
    """CLI --dry-run prints target path and does NOT remove anything."""

    def test_delete_cmd_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_temp_project(root, "Demo")
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
            backend = ProjectDiskBackend(settings)
            view = _demo_view()
            dest = backend.write_view("Demo", "Components/test-dryrun-tmp", view)
            self.assertTrue(dest.is_dir(), "write_view should have created the directory")
            try:
                with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-delete-tests",
                                             "IGNITION_DATA_DIR": str(root)}, clear=False):
                    from ignition_gen_sdk.cli import app
                    result = _runner().invoke(
                        app,
                        ["view", "delete",
                         "--project", "Demo",
                         "--view-path", "Components/test-dryrun-tmp",
                         "--dry-run",
                         "--no-scan"],
                    )
                self.assertEqual(result.exit_code, 0, msg=result.output)
                self.assertIn("Components/test-dryrun-tmp", result.output,
                              "dry-run output should mention the target path")
                self.assertTrue(dest.is_dir(),
                                "dry-run must not remove the directory")
            finally:
                import shutil
                if dest.exists():
                    shutil.rmtree(dest)


class TestDeleteCmdMissingPathExits1(unittest.TestCase):
    """CLI with a view-path that does not exist exits code 1 with 'not found' in output."""

    def test_delete_cmd_missing_path_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_temp_project(root, "Demo")
            with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-delete-tests",
                                         "IGNITION_DATA_DIR": str(root)}, clear=False):
                from ignition_gen_sdk.cli import app
                result = _runner().invoke(
                    app,
                    ["view", "delete",
                     "--project", "Demo",
                     "--view-path", "Components/definitely-does-not-exist-xyz",
                     "--no-scan"],
                )
            self.assertEqual(result.exit_code, 1, msg=result.output)
            combined = (result.output or "") + (getattr(result, "stderr", "") or "")
            self.assertTrue(
                "not found" in combined.lower() or "does not exist" in combined.lower(),
                f"Expected 'not found' in output. Got: {combined!r}"
            )


class TestDeleteCmdHelp(unittest.TestCase):
    """ign view delete --help exits 0 and mentions 'delete'."""

    def test_delete_cmd_help(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["view", "delete", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("delete", result.output.lower())
