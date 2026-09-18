"""Tests for the Perspective session-props model + ProjectDiskBackend writer +
`ign session-props declare`. Declares custom SESSION props (cross-view
shared state accessed via self.session.custom.*) — the 8.3-correct replacement
for the hallucinated system.perspective.setSessionProperty auto-create.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend, ProjectNotFoundError
from ignition_gen_sdk.config import Settings
from ignition_gen_sdk.models.session_props import SessionProps


def _settings_with_root(root: Path) -> Settings:
    return Settings(ignition_data_root=root)


def _make_project(root: Path, name: str) -> Path:
    proj = root / "projects" / name
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"title":"' + name + '"}')
    return proj


def test_props_json_shape() -> None:
    sp = SessionProps(custom={"app": {"selectedView": ""}})
    out = sp.props_json()
    assert out["custom"] == {"app": {"selectedView": ""}}
    assert out["propConfig"] == {} and out["props"] == {}


def test_write_session_props_creates_files(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    dest = backend.write_session_props("Proj", SessionProps(custom={"app": {"navHistory": []}}))
    assert (dest / "props.json").is_file()
    rj = json.loads((dest / "resource.json").read_text())
    assert rj["scope"] == "G" and rj["files"] == ["props.json"]
    written = json.loads((dest / "props.json").read_text())
    assert written["custom"]["app"]["navHistory"] == []


def test_read_session_props_empty_when_absent(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    assert backend.read_session_props("Proj").custom == {}


def test_declare_merges_custom(tmp_path: Path) -> None:
    _make_project(tmp_path, "Proj")
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    backend.write_session_props("Proj", SessionProps(custom={"app": {"a": 1}}))
    sp = backend.read_session_props("Proj")
    merged = dict(sp.custom)
    merged["other"] = {"b": 2}
    sp.custom = merged
    backend.write_session_props("Proj", sp)
    final = backend.read_session_props("Proj")
    assert set(final.custom) == {"app", "other"}


def test_write_session_props_missing_project_raises(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    backend = ProjectDiskBackend(_settings_with_root(tmp_path))
    with pytest.raises(ProjectNotFoundError):
        backend.write_session_props("Nope", SessionProps())


def test_cli_dry_run_shows_resource_json(tmp_path):
    """Session-props dry-run must preview the resource.json sidecar too
    (a real write emits props.json + resource.json) — faithful preview."""
    from typer.testing import CliRunner
    from ignition_gen_sdk.cli import app
    f = tmp_path / "sp.json"
    f.write_text('{"myFlag": {"dataType": "boolean", "value": false}}')
    r = CliRunner().invoke(
        app, ["session-props", "declare", "--project", "Demo",
              "--file", str(f), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "=== session-props/props.json" in r.output
    assert "=== session-props/resource.json ===" in r.output
    assert '"files"' in r.output


def test_declare_nested_prop_keeps_branch_siblings() -> None:
    """Declaring `nav.layout` must ADD a leaf, not replace the whole `nav` branch.

    A shallow update wiped session.custom.nav.{rootPath,title,kpis} the moment
    anyone declared a second prop under `nav` — silent data loss in the one
    command whose contract is "merged into existing custom props".
    """
    from ignition_gen_sdk.cli.cmd_session_props import _deep_merge

    existing = {
        "nav": {"rootPath": "[default]System", "title": "Plant", "kpis": [{"label": "Wet Well"}]},
        "scan": False,
    }
    merged = _deep_merge(existing, {"nav": {"layout": "auto"}})
    assert merged["nav"] == {
        "rootPath": "[default]System",
        "title": "Plant",
        "kpis": [{"label": "Wet Well"}],
        "layout": "auto",
    }
    assert merged["scan"] is False
    # Re-declaring a leaf still overwrites it, and the source dict is untouched.
    assert _deep_merge(merged, {"nav": {"layout": "desktop"}})["nav"]["layout"] == "desktop"
    assert "layout" not in existing["nav"]
