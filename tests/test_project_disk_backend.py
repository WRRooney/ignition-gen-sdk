"""Tests for ProjectDiskBackend."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ignition_gen_sdk.backends.project_disk import (
    ProjectDiskBackend,
    ProjectNotFoundError,
)
from ignition_gen_sdk.config import Settings
from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.view import View


def _make_view() -> View:
    return View(root=FlexContainer(
        meta=Meta(name="root"),
        props={"direction": "column"},
        children=[],
    ))


def _settings_with_root(root: Path) -> Settings:
    return Settings(ignition_data_root=root)


def _make_project_skeleton(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    (proj / "com.inductiveautomation.perspective" / "views").mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def test_write_view_creates_view_json_and_resource_json(tmp_path: Path):
    _make_project_skeleton(tmp_path, "Foo")
    settings = _settings_with_root(tmp_path)
    backend = ProjectDiskBackend(settings)
    dest = backend.write_view("Foo", "TestView", _make_view())

    assert dest == tmp_path / "projects" / "Foo" / "com.inductiveautomation.perspective" / "views" / "TestView"
    assert (dest / "view.json").is_file()
    assert (dest / "resource.json").is_file()

    view_data = json.loads((dest / "view.json").read_text())
    assert view_data["root"]["type"] == "ia.container.flex"

    resource_data = json.loads((dest / "resource.json").read_text())
    assert resource_data["scope"] == "G"
    # Files lists ONLY view.json. Pre-listing thumbnail.png
    # made the gateway throw NoSuchFileException + log an ERROR on every scan
    # (ign never writes the thumbnail); Designer adds it on first open.
    assert resource_data["files"] == ["view.json"]
    # LastModification.actor stamp identifies the writer.
    assert resource_data["attributes"]["lastModification"]["actor"] == "ign"


def test_write_view_raises_on_missing_project_skeleton(tmp_path: Path):
    """Fail loud when projects/<name>/project.json missing."""
    (tmp_path / "projects").mkdir()
    settings = _settings_with_root(tmp_path)
    backend = ProjectDiskBackend(settings)
    with pytest.raises(ProjectNotFoundError) as exc_info:
        backend.write_view("Bogus", "TestView", _make_view())
    assert "Designer first" in str(exc_info.value)


def test_write_view_auto_scaffolds_missing_views_dir(tmp_path: Path):
    """When project.json exists but the
    Perspective views directory is missing, write_view auto-creates it
    instead of raising. Replaces the previous fail-loud-on-missing-views/
    behavior. The project itself is still NOT auto-scaffolded — see
    test_write_view_still_raises_when_project_json_missing."""
    proj = tmp_path / "projects" / "PartialProj"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    settings = _settings_with_root(tmp_path)
    backend = ProjectDiskBackend(settings)
    dest = backend.write_view("PartialProj", "TestView", _make_view())
    assert (dest / "view.json").is_file()
    assert (dest / "resource.json").is_file()


def test_write_view_path_split_then_encoded_pitfall_5(tmp_path: Path):
    """--view-path A/B/C must produce 3 nested dirs, not 1 dir named A%2FB%2FC."""
    _make_project_skeleton(tmp_path, "Foo")
    settings = _settings_with_root(tmp_path)
    backend = ProjectDiskBackend(settings)
    dest = backend.write_view("Foo", "A/B/C", _make_view())
    expected = tmp_path / "projects" / "Foo" / "com.inductiveautomation.perspective" / "views" / "A" / "B" / "C"
    assert dest == expected
    assert (dest / "view.json").is_file()


def test_write_view_atomic_no_tmp_files_left_behind(tmp_path: Path):
    _make_project_skeleton(tmp_path, "Foo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_view("Foo", "AtomicTest", _make_view())
    leftovers = list(dest.glob("*.tmp"))
    assert leftovers == [], f"Found stray tmp files: {leftovers}"


def test_write_view_resolved_path_containment_for_happy_path(tmp_path: Path):
    """Defense-in-depth: dest.resolve() must sit under views_root.resolve()."""
    _make_project_skeleton(tmp_path, "Foo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_view("Foo", "Main/Overview", _make_view())
    views_root = (tmp_path / "projects" / "Foo"
                  / "com.inductiveautomation.perspective" / "views")
    assert views_root.resolve() in dest.resolve().parents


# ----------------------------------------------------------------------------
# Auto-scaffold perspective views/ subdir
# ----------------------------------------------------------------------------

def _setup_project_no_perspective(root: Path, name: str) -> Path:
    """project.json present; com.inductiveautomation.perspective/ absent."""
    proj = root / "projects" / name
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def _setup_project_no_views(root: Path, name: str) -> Path:
    """project.json present; com.inductiveautomation.perspective/ present; views/ absent."""
    proj = root / "projects" / name
    (proj / "com.inductiveautomation.perspective").mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def test_write_view_auto_creates_missing_perspective_views_dir(tmp_path: Path):
    """When project.json present but com.inductiveautomation.perspective/
    is fully missing, write_view mkdir's the whole subtree and writes."""
    _setup_project_no_perspective(tmp_path, "Foo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_view("Foo", "Main/Overview", _make_view())
    assert (
        dest
        == tmp_path
        / "projects"
        / "Foo"
        / "com.inductiveautomation.perspective"
        / "views"
        / "Main"
        / "Overview"
    )
    assert (dest / "view.json").is_file()
    assert (dest / "resource.json").is_file()


def test_write_view_auto_creates_only_views_dir_when_perspective_present(tmp_path: Path):
    """When perspective/ exists but views/ does not, mkdir views/."""
    _setup_project_no_views(tmp_path, "Foo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_view("Foo", "Main/Overview", _make_view())
    assert (dest / "view.json").is_file()
    assert (dest / "resource.json").is_file()
    views_root = (
        tmp_path
        / "projects"
        / "Foo"
        / "com.inductiveautomation.perspective"
        / "views"
    )
    assert views_root.is_dir()


def test_write_view_still_raises_when_project_json_missing(tmp_path: Path):
    """Missing project.json still fails loud."""
    proj = tmp_path / "projects" / "Foo"
    proj.mkdir(parents=True)
    # NO project.json file written
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ProjectNotFoundError) as exc_info:
        backend.write_view("Foo", "X/Y", _make_view())
    msg = str(exc_info.value)
    assert "Foo" in msg
    assert "not found" in msg


def test_write_view_happy_path_unchanged_when_views_dir_present(tmp_path: Path):
    """Existing happy path stays green: views/ already exists, no new mkdir cost."""
    _make_project_skeleton(tmp_path, "Foo")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_view("Foo", "Main/Overview", _make_view())
    assert (dest / "view.json").is_file()
    assert (dest / "resource.json").is_file()


# ----------------------------------------------------------------------------
# _split_view_path_segments helper unification
# ----------------------------------------------------------------------------

def test_split_view_path_segments_rejects_traversal_and_empty():
    """Direct unit test of the new helper. Rejects empty, whitespace, '.', '..',
    and net-empty paths; accepts inner-empty skips."""
    from ignition_gen_sdk.backends.project_disk import _split_view_path_segments

    # Reject cases
    for bad in ["", "   ", ".", "..", "foo/..", "../escape", "/", "//"]:
        with pytest.raises(ValueError):
            _split_view_path_segments(bad)

    # Accept cases — inner empties skipped
    assert _split_view_path_segments("Main/Overview") == ["Main", "Overview"]
    assert _split_view_path_segments("//foo//") == ["foo"]


def test_write_view_uses_single_segment_helper():
    """Regression: write_view must call _split_view_path_segments and
    must NOT contain the duplicated pre-loop and in-loop empty-segment filters."""
    import inspect

    from ignition_gen_sdk.backends import project_disk as pd

    src = inspect.getsource(pd.write_view if False else pd.ProjectDiskBackend.write_view)
    # The single canonical call site exists
    assert "_split_view_path_segments" in src
    # The duplicated parallel filters are gone
    assert "non_empty_segments" not in src
    assert "for s in view_path.split" not in src
