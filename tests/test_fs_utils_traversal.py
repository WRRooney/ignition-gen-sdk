"""Regression tests for path-traversal and empty-path handling in the disk
backends and the view-write CLI."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ignition_gen_sdk.backends._fs_utils import _encode_segment
from ignition_gen_sdk.backends.disk_backend import DiskBackend
from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
from ignition_gen_sdk.cli.cmd_view import view_app
from ignition_gen_sdk.config import Settings
from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.view import View


# ---- _encode_segment unit guards ----

def test_encode_segment_rejects_dotdot():
    with pytest.raises(ValueError, match=r"\.\."):
        _encode_segment("..")


def test_encode_segment_rejects_dot():
    with pytest.raises(ValueError):
        _encode_segment(".")


def test_encode_segment_rejects_empty():
    with pytest.raises(ValueError):
        _encode_segment("")


def test_encode_segment_rejects_whitespace():
    with pytest.raises(ValueError):
        _encode_segment("   ")
    with pytest.raises(ValueError):
        _encode_segment("\t")


def test_encode_segment_passes_through_valid():
    assert _encode_segment("foo") == "foo"
    assert _encode_segment("Main") == "Main"


def test_encode_segment_rejects_inner_slash():
    # The encoder no longer silently percent-encodes
    # inner '/' to '%2F'. A segment containing '/' is multi-segment
    # misuse and must be rejected so the caller passes each piece
    # separately. This is what makes "Home Large" a single literal
    # directory (no %20) instead of "Home/Large" sneaking through.
    with pytest.raises(ValueError, match="forbidden"):
        _encode_segment("../local")


def test_encode_segment_preserves_literal_space():
    # Gateway uses literal spaces in disk paths. ASCII spaces
    # must NOT be percent-encoded.
    assert _encode_segment("Home Large") == "Home Large"
    assert _encode_segment("MQTT Engine") == "MQTT Engine"


def test_encode_segment_encodes_colon():
    # Only ':' is substituted, and only with lowercase %3a (matches
    # gateway-emitted MQTT Engine fixtures like 'light%3a0').
    assert _encode_segment("light:0") == "light%3a0"


# ---- ProjectDiskBackend integration guards ----

def _make_project_skeleton(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    (proj / "com.inductiveautomation.perspective" / "views").mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def _make_view() -> View:
    return View(root=FlexContainer(
        meta=Meta(name="root"),
        props={"direction": "column"},
        children=[],
    ))


def _backend_for(tmp_path: Path) -> ProjectDiskBackend:
    _make_project_skeleton(tmp_path, "Foo")
    return ProjectDiskBackend(Settings(ignition_data_root=tmp_path))


@pytest.mark.parametrize("bad", ["", "/", "   ", "\t", "  / "])
def test_write_view_rejects_empty_or_whitespace_view_path(tmp_path, bad):
    backend = _backend_for(tmp_path)
    with pytest.raises(ValueError):
        backend.write_view("Foo", bad, _make_view())


@pytest.mark.parametrize("bad", [
    "../escape",
    "foo/../../escape",
    ".",
    "./foo",
    "foo/./bar",
])
def test_write_view_rejects_traversal_segments(tmp_path, bad):
    backend = _backend_for(tmp_path)
    with pytest.raises(ValueError):
        backend.write_view("Foo", bad, _make_view())


def test_write_view_preserves_inner_empty_segments(tmp_path):
    backend = _backend_for(tmp_path)
    dest = backend.write_view("Foo", "//foo//", _make_view())
    expected = (tmp_path / "projects" / "Foo"
                / "com.inductiveautomation.perspective" / "views" / "foo")
    assert dest == expected
    assert (dest / "view.json").is_file()


def test_write_view_containment_check_holds_for_happy_path(tmp_path):
    backend = _backend_for(tmp_path)
    dest = backend.write_view("Foo", "Main/Overview", _make_view())
    views_root = (tmp_path / "projects" / "Foo"
                  / "com.inductiveautomation.perspective" / "views")
    assert views_root.resolve() in dest.resolve().parents


# ---- Regression: literal spaces in disk paths ----

def test_write_view_preserves_literal_space_in_path(tmp_path):
    """Writing a view at 'Home/Home Large' must land in
    a directory named literally 'Home Large' (no %20). The gateway uses
    literal spaces in samplequickstart fixtures like
    Home/Home Large/view.json; percent-encoded variants are NOT
    recognized.
    """
    backend = _backend_for(tmp_path)
    dest = backend.write_view("Foo", "Home/Home Large", _make_view())
    expected = (tmp_path / "projects" / "Foo"
                / "com.inductiveautomation.perspective"
                / "views" / "Home" / "Home Large")
    assert dest == expected, f"expected literal-space directory, got {dest!r}"
    assert dest.is_dir(), f"directory {dest!r} was not created"
    assert (dest / "view.json").is_file()
    # Defense-in-depth: the percent-encoded variant must NOT exist.
    pct = (tmp_path / "projects" / "Foo"
           / "com.inductiveautomation.perspective"
           / "views" / "Home" / "Home%20Large")
    assert not pct.exists(), (
        f"percent-encoded fallback directory {pct!r} was created — "
        f"regression: _encode_segment percent-encoded a literal space."
    )


# ---- DiskBackend surface ----

def _disk_backend_for(tmp_path: Path) -> DiskBackend:
    return DiskBackend(Settings(ignition_data_root=tmp_path))


@pytest.mark.parametrize("bad_provider", ["..", ".", "", "   "])
def test_tag_def_path_rejects_bad_provider(tmp_path, bad_provider):
    backend = _disk_backend_for(tmp_path)
    with pytest.raises(ValueError):
        backend._tag_def_path(bad_provider, "Tanks/T01")


@pytest.mark.parametrize("bad_path", [
    "../escape",
    "Tanks/../../etc",
    "Tanks/./T01",
    ".",
])
def test_tag_def_path_rejects_bad_path(tmp_path, bad_path):
    backend = _disk_backend_for(tmp_path)
    with pytest.raises(ValueError):
        backend._tag_def_path("default", bad_path)


# ---- CLI surface — full end-to-end through typer.testing ----

def _patch_settings(monkeypatch, tmp_path: Path) -> None:
    """Patch Settings constructor so cmd_view.write_cmd uses tmp_path.

    `monkeypatch.setattr(cmd_view, "Settings", ...)` is correct because
    `cmd_view.py` imports `Settings` directly into its module namespace
    (verified: cmd_view.py has `from ..config import Settings`).
    """
    import ignition_gen_sdk.cli.cmd_view as cmd_view
    monkeypatch.setattr(
        cmd_view, "Settings",
        lambda: Settings(ignition_data_root=tmp_path),
    )


def test_cli_view_write_rejects_empty_view_path(tmp_path, monkeypatch):
    _make_project_skeleton(tmp_path, "SmokeProj")
    _patch_settings(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        view_app,
        ["write", "--project", "SmokeProj", "--view-path", "", "--no-dry-run"],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "view-path" in combined.lower() or "empty" in combined.lower()


def test_cli_view_write_rejects_traversal_view_path(tmp_path, monkeypatch):
    _make_project_skeleton(tmp_path, "SmokeProj")
    _patch_settings(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        view_app,
        ["write", "--project", "SmokeProj",
         "--view-path", "../../../escape/pwn", "--no-dry-run"],
    )
    assert result.exit_code != 0
    # No file landed outside views root.
    assert not (tmp_path / "projects" / "escape").exists()
