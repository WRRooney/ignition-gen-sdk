"""Tests for the Perspective page-config model + ProjectDiskBackend writer +
`ign page mount`. Mounts a view at a URL — the entry-point config a
Perspective project needs to render anything. Filesystem writes go to tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ignition_gen_sdk.config import Settings
from ignition_gen_sdk.models.page_config import PageConfig, PageEntry

import pytest


def _settings_with_root(root: Path) -> Settings:
    return Settings(ignition_data_root=root)


def _make_project(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


# --- model ---


def test_config_json_shape_and_title_dropped_when_none() -> None:
    cfg = PageConfig(pages={"/": PageEntry(viewPath="Components/Overview")})
    out = cfg.config_json()
    assert out["pages"]["/"] == {"viewPath": "Components/Overview"}  # no null title
    assert out["sharedDocks"] == {"cornerPriority": "top-bottom"}


def test_config_json_keeps_title() -> None:
    cfg = PageConfig().with_page("/pid", "Area1/PID", title="P&ID")
    assert cfg.config_json()["pages"]["/pid"] == {
        "viewPath": "Area1/PID",
        "title": "P&ID",
    }


def test_with_page_preserves_existing() -> None:
    cfg = PageConfig().with_page("/", "A").with_page("/pid", "B")
    assert set(cfg.pages) == {"/", "/pid"}
    # replace one, keep the other
    cfg2 = cfg.with_page("/", "C")
    assert cfg2.pages["/"].viewPath == "C"
    assert cfg2.pages["/pid"].viewPath == "B"


# --- backend ---


def test_write_page_config_creates_files(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    cfg = PageConfig().with_page("/", "Components/Overview", title="Overview")
    dest = backend.write_page_config("Proj", cfg)
    assert (dest / "config.json").is_file()
    rj = json.loads((dest / "resource.json").read_text())
    assert rj["scope"] == "G"
    assert rj["files"] == ["config.json"]
    written = json.loads((dest / "config.json").read_text())
    assert written["pages"]["/"]["viewPath"] == "Components/Overview"


def test_read_page_config_empty_when_absent(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    assert backend.read_page_config("Proj").pages == {}


def test_read_after_write_roundtrips_and_merges(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    backend.write_page_config("Proj", PageConfig().with_page("/", "Home"))
    # incremental mount: read existing, add, write
    merged = backend.read_page_config("Proj").with_page("/pid", "Sim/PID", title="PID")
    backend.write_page_config("Proj", merged)
    final = backend.read_page_config("Proj")
    assert set(final.pages) == {"/", "/pid"}
    assert final.pages["/"].viewPath == "Home"
    assert final.pages["/pid"].title == "PID"


def test_write_page_config_missing_project_raises(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ProjectNotFoundError):
        backend.write_page_config("Nope", PageConfig())


def test_cli_dry_run_shows_resource_json():
    """Page dry-run must preview the resource.json sidecar too
    (a real write emits config.json + resource.json) — faithful preview."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app
    r = CliRunner().invoke(
        app, ["page", "mount", "--project", "Demo", "--url", "/demo",
              "--view-path", "Components/Overview", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "=== page-config/config.json" in r.output
    assert "=== page-config/resource.json ===" in r.output
