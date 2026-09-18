"""A read must never create a Perspective resource DIRECTORY.

Perspective inherits page-config and session-props per RESOURCE, and it treats
the DIRECTORY as the resource. A child project left holding an empty
page-config/ shadows its parent's routes completely: every route added to the
parent 404s, and no amount of scanning fixes it.

That is not hypothetical. `ign page list` -- a read-only command -- used to
auto-mkdir the directory, which silently broke route inheritance on this
gateway and produced a symptom (a route that will not resolve) that looks
nothing like its cause.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _project(root: Path, name: str = "Child") -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"%s"}' % name)
    return proj


def _backend(root: Path):
    with patch.dict(os.environ,
                    {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
                    clear=False):
        from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
        from ignition_gen_sdk.config import Settings

        return ProjectDiskBackend(Settings())  # type: ignore[call-arg]


def _invoke(root: Path, args):
    with patch.dict(os.environ,
                    {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
                    clear=False):
        from typer.testing import CliRunner

        from ignition_gen_sdk.cli import app

        return CliRunner().invoke(app, args)


class TestReadsDoNotCreate(unittest.TestCase):
    def _perspective(self, root: Path) -> Path:
        return (root / "projects" / "Child" / "com.inductiveautomation.perspective")

    def test_read_page_config_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root)
            _backend(root).read_page_config("Child")
            self.assertFalse((self._perspective(root) / "page-config").exists())

    def test_read_session_props_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root)
            _backend(root).read_session_props("Child")
            self.assertFalse((self._perspective(root) / "session-props").exists())

    def test_page_list_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root)
            res = _invoke(root, ["page", "list", "--project", "Child"])
            self.assertEqual(res.exit_code, 0, msg=res.output)
            self.assertFalse(
                (self._perspective(root) / "page-config").exists(),
                "listing pages must not create the resource that shadows the "
                "parent's routes")

    def test_writes_still_create_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root)
            backend = _backend(root)
            from ignition_gen_sdk.models.page_config import PageConfig
            from ignition_gen_sdk.models.session_props import SessionProps

            backend.write_page_config("Child", PageConfig().with_page(
                "/", "Some/View", "Title"))
            backend.write_session_props("Child", SessionProps(custom={"a": 1}))
            self.assertTrue((self._perspective(root) / "page-config"
                             / "config.json").is_file())
            self.assertTrue((self._perspective(root) / "session-props"
                             / "props.json").is_file())


if __name__ == "__main__":
    unittest.main()
