"""ign script delete — backend behavior."""

import pytest

from ignition_gen_sdk.backends.project_disk import (
    ProjectDiskBackend,
    ScriptNotFoundError,
)


class _S:  # minimal settings stub
    def __init__(self, root):
        self.projects_root = root


def _mk_backend(tmp_path, monkeypatch):
    proj = tmp_path / "projects" / "P"
    (proj / "ignition" / "script-python" / "library" / "x").mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    (proj / "ignition" / "script-python" / "library" / "x" / "code.py").write_text("\tpass\n")
    (proj / "ignition" / "script-python" / "library" / "x" / "resource.json").write_text("{}")
    b = ProjectDiskBackend.__new__(ProjectDiskBackend)
    b._projects_root = tmp_path / "projects"
    return b, proj


def test_delete_script_removes_and_prunes(tmp_path, monkeypatch):
    b, proj = _mk_backend(tmp_path, monkeypatch)
    b.delete_script("P", "library/x")
    assert not (proj / "ignition" / "script-python" / "library").exists()  # pruned
    assert (proj / "ignition" / "script-python").exists()  # root untouched


def test_delete_script_missing_raises(tmp_path, monkeypatch):
    b, _ = _mk_backend(tmp_path, monkeypatch)
    with pytest.raises(ScriptNotFoundError):
        b.delete_script("P", "library/nope")
