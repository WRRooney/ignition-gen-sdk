"""write_style_class: shape guard, placement, resource sidecar,
containment; plus write_view's thumbnail-manifest preservation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend
from ignition_gen_sdk.models.views.view import View


class _Settings:
    def __init__(self, root: Path) -> None:
        self.ignition_data_root = root


def _backend(root: Path) -> ProjectDiskBackend:
    proj = root / "projects" / "Demo"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    return ProjectDiskBackend(_Settings(root))  # type: ignore[arg-type]


STYLE = {"base": {"style": {"transition": "all 0.1s"}},
         "variants": [{"pseudo": "hover", "style": {"backgroundColor": "var(--neutral-30)"}}]}


def test_write_style_class_places_files_and_sidecar():
    with tempfile.TemporaryDirectory() as d:
        dest = _backend(Path(d)).write_style_class("Demo", "table-item", STYLE)
        assert dest == Path(d) / "projects/Demo/com.inductiveautomation.perspective/style-classes/table-item"
        assert json.loads((dest / "style.json").read_text()) == STYLE
        res = json.loads((dest / "resource.json").read_text())
        assert res["files"] == ["style.json"] and res["scope"] == "G"


def test_write_style_class_rejects_unknown_top_level_key():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="unknown top-level"):
            _backend(Path(d)).write_style_class("Demo", "x", {"base": {}, "styel": {}})


def test_write_style_class_rejects_escape_path():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError):
            _backend(Path(d)).write_style_class("Demo", "../../evil", STYLE)


def test_write_view_preserves_and_heals_thumbnail_manifest():
    view = View.model_validate({"custom": {}, "params": {}, "props": {},
                                "root": {"meta": {"name": "root"}, "props": {},
                                         "type": "ia.container.flex"}})
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        dest = be.write_view("Demo", "A/B", view)
        assert json.loads((dest / "resource.json").read_text())["files"] == ["view.json"]
        # Designer drops a thumbnail; a rewrite must list it (heal-from-disk)
        (dest / "thumbnail.png").write_bytes(b"png")
        be.write_view("Demo", "A/B", view)
        assert json.loads((dest / "resource.json").read_text())["files"] == [
            "view.json", "thumbnail.png"]

def test_delete_style_class_removes_it_and_errors_when_absent():
    """Generated classes go stale when a generator stops emitting them, and a
    stale class keeps applying to anything still naming it — so pruning needs a
    sanctioned path."""
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        dest = be.write_style_class("Demo", "nav-crumb-current", STYLE)
        assert dest.is_dir()

        removed = be.delete_style_class("Demo", "nav-crumb-current")
        assert not removed.exists()

        with pytest.raises(FileNotFoundError, match="not found"):
            be.delete_style_class("Demo", "nav-crumb-current")


def test_delete_style_class_rejects_escape_path():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError):
            _backend(Path(d)).delete_style_class("Demo", "../../evil")
if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
