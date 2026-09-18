"""A generator must not silently overwrite a view someone has edited.

Every build_*.py is a SEED: it writes the first version of a view family and
the owner then refines those views in the Designer. The rule is "never re-run
a generator over a user-edited view", but nothing enforced it --
running one with no arguments rewrote the whole family, and recovery was
`git checkout` if you were lucky enough to have committed.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch



def _backend(root: Path):
    with patch.dict(os.environ,
                    {"IGNITION_API_TOKEN": "test:dummy", "IGNITION_DATA_DIR": str(root)},
                    clear=False):
        from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
        from ignition_gen_sdk.config import Settings

        return ProjectDiskBackend(Settings())  # type: ignore[call-arg]


def _seed(root: Path, *view_paths: str) -> None:
    proj = root / "projects" / "Demo"
    (proj).mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text('{"title":"Demo"}')
    for vp in view_paths:
        d = proj / "com.inductiveautomation.perspective" / "views"
        for seg in vp.split("/"):
            d = d / seg
        d.mkdir(parents=True, exist_ok=True)
        (d / "view.json").write_text("{}")


class TestSeedGuard(unittest.TestCase):
    def test_refuses_when_a_target_exists(self):
        from ignition_gen_sdk.tools.seed_guard import guard

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(root, "Alarm/Chip")
            with self.assertRaises(SystemExit) as ctx:
                guard(_backend(root), "Demo",
                      ["Alarm/Chip", "Alarm/Kpi"], force=False)
            self.assertEqual(ctx.exception.code, 2)

    def test_allows_a_clean_run(self):
        from ignition_gen_sdk.tools.seed_guard import guard

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(root)
            guard(_backend(root), "Demo", ["Alarm/Chip"], force=False)

    def test_force_overrides(self):
        from ignition_gen_sdk.tools.seed_guard import guard

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(root, "Alarm/Chip")
            guard(_backend(root), "Demo", ["Alarm/Chip"], force=True)

    def test_only_reports_paths_that_exist(self):
        from ignition_gen_sdk.tools.seed_guard import existing_views

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(root, "Alarm/Chip", "Roster/Entry")
            found = existing_views(_backend(root), "Demo",
                                   ["Alarm/Chip", "Alarm/Nope", "Roster/Entry"])
            self.assertEqual(found, ["Alarm/Chip", "Roster/Entry"])

    def test_a_directory_without_view_json_is_not_a_view(self):
        # view delete prunes empty folders, but a stray directory must not make
        # the guard refuse a legitimate first run.
        from ignition_gen_sdk.tools.seed_guard import existing_views

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed(root)
            (root / "projects/Demo/com.inductiveautomation.perspective"
             / "views/Alarm/Chip").mkdir(parents=True)
            self.assertEqual(
                existing_views(_backend(root), "Demo", ["Alarm/Chip"]), [])


if __name__ == "__main__":
    unittest.main()
