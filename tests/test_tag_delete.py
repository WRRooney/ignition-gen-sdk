"""Tests for DiskBackend.delete_tag + ign tag delete CLI.

All tests are self-contained using tmp_path / tempfile — no dependency on
existing gateway files. Tests mirror test_view_delete.py structure.

Test IDs:
  - test_delete_tag_removes_dir
  - test_delete_tag_nonexistent_raises
  - test_delete_cmd_dry_run
  - test_delete_cmd_missing_path_exits_1
  - test_delete_cmd_layer_guard_rejects_traversal
  - test_delete_cmd_help
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


def _settings_with_root(root: Path):
    """Build a Settings whose ignition_data_root is a temp directory."""
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-delete-tests"}, clear=False):
        from ignition_gen_sdk.config import Settings
        return Settings(ignition_data_root=root)


def _write_dummy_tag_def(root: Path, provider: str, path: str) -> Path:
    """Write a minimal tag-definition dir so delete_tag has something to find."""
    tag_def_root = root / "config" / "resources" / "core" / "ignition" / "tag-definition"
    dest = tag_def_root / provider
    for seg in path.split("/"):
        if seg:
            dest = dest / seg
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "tags.json").write_text(json.dumps({"name": "root", "tagType": "Provider", "tags": []}))
    (dest / "unary-resource.json").write_text(json.dumps({"scope": "G", "version": 1, "files": ["tags.json"]}))
    return dest


class TestDeleteTagRemovesDir(unittest.TestCase):
    """delete_tag removes the tag-definition directory from disk."""

    def test_delete_tag_removes_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.disk_backend import DiskBackend
            backend = DiskBackend(settings)

            # Write a real tag definition then delete it
            from ignition_gen_sdk.models.tags.enums.tag_type import TagType
            from ignition_gen_sdk.models.tags.tag import Tag
            tag = Tag(name="TestFolder", tagType=TagType.FOLDER)
            dest = backend.write_tags("default", "Smoke/TestDeleteDir", [tag])
            self.assertTrue(dest.is_dir(), "write_tags should have created the directory")

            backend.delete_tag("default", "Smoke/TestDeleteDir")
            self.assertFalse(dest.exists(), "delete_tag should have removed the directory")


class TestDeleteTagNonexistentRaises(unittest.TestCase):
    """delete_tag raises TagNotFoundError on a path that does not exist."""

    def test_delete_tag_nonexistent_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.disk_backend import DiskBackend, TagNotFoundError
            backend = DiskBackend(settings)
            with self.assertRaises((TagNotFoundError, FileNotFoundError)):
                backend.delete_tag("default", "Does/NotExist")


class TestDeleteCmdDryRun(unittest.TestCase):
    """CLI --dry-run prints target path and does NOT remove anything."""

    def test_delete_cmd_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = _write_dummy_tag_def(root, "default", "Smoke/DryRunTest")
            self.assertTrue(dest.is_dir(), "Setup: tag-def dir should exist")
            try:
                from ignition_gen_sdk.cli import app
                result = _runner().invoke(
                    app,
                    ["tag", "delete",
                     "--provider", "default",
                     "--path", "Smoke/DryRunTest",
                     "--dry-run",
                     "--no-scan"],
                )
                self.assertEqual(result.exit_code, 0, msg=result.output)
                self.assertIn("Smoke/DryRunTest", result.output,
                              "dry-run output should mention the target path")
                self.assertIn("Would delete", result.output,
                              "dry-run output should say 'Would delete'")
                self.assertTrue(dest.is_dir(),
                                "dry-run must not remove the directory")
            finally:
                import shutil
                if dest.exists():
                    shutil.rmtree(dest)


class TestDeleteCmdMissingPathExits1(unittest.TestCase):
    """CLI with a path that does not exist exits code 1 with 'not found' in output."""

    def test_delete_cmd_missing_path_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ,
                            {"IGNITION_API_TOKEN": "test:dummy-for-delete-tests",
                             "IGNITION_DATA_DIR": str(root)},
                            clear=False):
                from ignition_gen_sdk.cli import app
                result = _runner().invoke(
                    app,
                    ["tag", "delete",
                     "--provider", "default",
                     "--path", "Does/NotExist/AtAll",
                     "--no-scan"],
                )
            self.assertEqual(result.exit_code, 1, msg=result.output)
            combined = (result.output or "") + (getattr(result, "stderr", "") or "")
            self.assertTrue(
                "not found" in combined.lower() or "does not exist" in combined.lower(),
                f"Expected 'not found' in output. Got: {combined!r}"
            )


class TestDeleteCmdLayerGuardRejectsTraversal(unittest.TestCase):
    """CLI layer guard: path traversal segments raise ValueError, exit 1."""

    def test_delete_cmd_layer_guard_rejects_traversal(self):
        with tempfile.TemporaryDirectory():
            # Use dry-run so no Settings/IO needed — the layer guard fires in _encode_segment
            from ignition_gen_sdk.cli import app
            result = _runner().invoke(
                app,
                ["tag", "delete",
                 "--provider", "default",
                 "--path", "../etc/passwd",
                 "--dry-run",
                 "--no-scan"],
            )
            self.assertEqual(result.exit_code, 1, msg=result.output)
            combined = (result.output or "") + (getattr(result, "stderr", "") or "")
            self.assertTrue(
                "invalid" in combined.lower()
                or "traversal" in combined.lower()
                or "forbidden" in combined.lower()
                or "error" in combined.lower(),
                f"Expected error message about invalid path. Got: {combined!r}"
            )


class TestDeleteCmdHelp(unittest.TestCase):
    """ign tag delete --help exits 0 and mentions 'delete'."""

    def test_delete_cmd_help(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(app, ["tag", "delete", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("delete", result.output.lower())
        # Should mention --provider and --path
        self.assertIn("provider", result.output.lower())
        self.assertIn("path", result.output.lower())


class TestDeleteCmdDryRunKindType(unittest.TestCase):
    """CLI --kind type --dry-run targets tag-type-definition, not tag-definition."""

    def test_delete_cmd_dry_run_kind_type(self):
        from ignition_gen_sdk.cli import app
        result = _runner().invoke(
            app,
            ["tag", "delete",
             "--provider", "default",
             "--path", "Reports",
             "--kind", "type",
             "--dry-run",
             "--no-scan"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("tag-type-definition/default/Reports", result.output)
        self.assertNotIn("tag-definition/default/Reports", result.output)


def _write_dummy_udt_type_def(root: Path, provider: str, path: str) -> Path:
    """Write a minimal tag-type-definition dir so delete_udt_type has something to find."""
    type_def_root = root / "config" / "resources" / "core" / "ignition" / "tag-type-definition"
    dest = type_def_root / provider
    for seg in path.split("/"):
        if seg:
            dest = dest / seg
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "udts.json").write_text(
        json.dumps([{"name": "Dummy", "tagType": "UdtType", "typeId": "_Global", "tags": []}])
    )
    (dest / "unary-resource.json").write_text(json.dumps({"scope": "G", "version": 1, "files": ["udts.json"]}))
    return dest


class TestDeleteUdtType(unittest.TestCase):
    """DiskBackend.delete_udt_type removes a tag-type-definition dir; raises when absent."""

    def test_delete_udt_type_removes_dir_and_raises_for_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings_with_root(root)
            from ignition_gen_sdk.backends.disk_backend import DiskBackend, TagNotFoundError
            backend = DiskBackend(settings)

            dest = _write_dummy_udt_type_def(root, "default", "Smoke/TestDeleteUdtType")
            self.assertTrue(dest.is_dir(), "Setup: tag-type-definition dir should exist")

            backend.delete_udt_type("default", "Smoke/TestDeleteUdtType")
            self.assertFalse(dest.exists(), "delete_udt_type should have removed the directory")

            with self.assertRaises((TagNotFoundError, FileNotFoundError)):
                backend.delete_udt_type("default", "Does/NotExist")
