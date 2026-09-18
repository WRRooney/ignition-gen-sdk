"""Tests for `ign page list`.

The clean-room agent reflexively tried `ign page list` to confirm a page was
mounted before rendering it; only `page mount` (write) existed. `page list` is
read-only: it reads the project's page-config and reports the mounted URLs.

Test IDs:
  - test_page_list_empty
  - test_page_list_shows_pages
  - test_page_list_json
  - test_page_list_project_not_found_exits_1
  - test_page_list_help
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


def _make_project(root: Path, name: str = "Demo") -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def _write_pages(root: Path, project: str) -> None:
    """Seed a 2-page page-config via the sanctioned backend writer."""
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)}, clear=False):
        from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
        from ignition_gen_sdk.config import Settings
        from ignition_gen_sdk.models.page_config import PageConfig

        backend = ProjectDiskBackend(Settings())  # type: ignore[call-arg]
        cfg = PageConfig().with_page("/", "Components/Overview", "Overview").with_page(
            "/pid", "Area1/PID", "Area1 P&ID"
        )
        backend.write_page_config(project, cfg)


def _invoke(root: Path, args: list[str]):
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)}, clear=False):
        from ignition_gen_sdk.cli import app
        return _runner().invoke(app, args)


class TestPageList(unittest.TestCase):
    def test_page_list_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            res = _invoke(root, ["page", "list", "--project", "Demo"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertIn("No pages mounted", res.output)
            self.assertIn("ign page mount", res.output)  # actionable hint

    def test_page_list_shows_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            _write_pages(root, "Demo")
            res = _invoke(root, ["page", "list", "--project", "Demo"])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertIn("2 page(s)", res.output)
            self.assertIn("/pid", res.output)
            self.assertIn("Area1/PID", res.output)
            self.assertIn("Components/Overview", res.output)
            self.assertIn("Area1 P&ID", res.output)  # title rendered

    def test_page_list_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_project(root, "Demo")
            _write_pages(root, "Demo")
            res = _invoke(root, ["page", "list", "--project", "Demo", "--json"])
            self.assertEqual(res.exit_code, 0, res.output)
            data = json.loads(res.output)
            self.assertEqual(data["/"]["viewPath"], "Components/Overview")
            self.assertEqual(data["/pid"]["viewPath"], "Area1/PID")
            self.assertEqual(data["/pid"]["title"], "Area1 P&ID")

    def test_page_list_project_not_found_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # no project created
            res = _invoke(root, ["page", "list", "--project", "Nope"])
            self.assertEqual(res.exit_code, 1, res.output)

    def test_page_list_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = _invoke(Path(tmp), ["page", "list", "--help"])
            self.assertEqual(res.exit_code, 0)
            self.assertIn("--project", res.output)
            self.assertIn("--json", res.output)


if __name__ == "__main__":
    unittest.main()
