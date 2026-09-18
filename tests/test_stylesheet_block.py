"""write_stylesheet_block: idempotent marker blocks that never disturb the
hand-authored CSS around them (the Designer stylesheet is user territory)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend

HAND = "/* ==================== VARIABLES ==================== */\n:root { --x: 1px; }\n"


class _Settings:
    def __init__(self, root: Path) -> None:
        self.ignition_data_root = root


def _backend(root: Path) -> ProjectDiskBackend:
    proj = root / "projects" / "Demo"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    return ProjectDiskBackend(_Settings(root))  # type: ignore[arg-type]


def test_upsert_appends_then_replaces_in_place():
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        css_path = Path(d) / "projects/Demo/com.inductiveautomation.perspective/stylesheet/stylesheet.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text(HAND)

        be.write_stylesheet_block("Demo", "nav", ".a { color: red; }")
        first = css_path.read_text()
        assert first.startswith(HAND)  # hand-authored CSS untouched
        assert ".a { color: red; }" in first

        be.write_stylesheet_block("Demo", "nav", ".a { color: blue; }")
        second = css_path.read_text()
        assert second.startswith(HAND)
        assert "color: red" not in second and "color: blue" in second
        assert second.count("ign:nav */") == 2  # exactly one block (open+close)


def test_second_marker_appends_without_touching_the_first():
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        be.write_stylesheet_block("Demo", "one", ".one {}")
        dest = be.write_stylesheet_block("Demo", "two", ".two {}")
        css = (dest / "stylesheet.css").read_text()
        assert ".one {}" in css and ".two {}" in css
        assert json.loads((dest / "resource.json").read_text())["files"] == ["stylesheet.css"]


def test_creates_stylesheet_when_project_has_none():
    with tempfile.TemporaryDirectory() as d:
        dest = _backend(Path(d)).write_stylesheet_block("Demo", "nav", ".a {}")
        assert (dest / "stylesheet.css").read_text().startswith("/* >>> ign:nav */")


@pytest.mark.parametrize("marker", ["", "bad marker", "a" * 65, "nav/x"])
def test_rejects_bad_markers(marker):
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="marker"):
            _backend(Path(d)).write_stylesheet_block("Demo", marker, ".a {}")


def test_rejects_payload_containing_block_delimiters():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match="delimiters"):
            _backend(Path(d)).write_stylesheet_block(
                "Demo", "nav", "/* >>> ign:other */ .a {}")


def test_remove_deletes_only_its_block_and_leaves_the_hand_css():
    """Removing is how a marker gets RENAMED: upsert under the new name, then
    remove the old. An upsert cannot do it -- empty content is refused, and
    would leave an empty block behind anyway."""
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        dest = be.write_stylesheet_block("Demo", "old", ".gone {}")
        css_path = dest / "stylesheet.css"
        css_path.write_text(HAND + "\n" + css_path.read_text())
        be.write_stylesheet_block("Demo", "keep", ".stays {}")

        assert be.remove_stylesheet_block("Demo", "old") is True
        css = css_path.read_text()
        assert HAND in css                       # hand-authored CSS survives
        assert ".gone {}" not in css and "ign:old" not in css
        assert ".stays {}" in css and css.count("ign:keep */") == 2
        assert "\n\n\n" not in css               # no blank-line crater


def test_remove_is_idempotent_and_validates_the_marker():
    with tempfile.TemporaryDirectory() as d:
        be = _backend(Path(d))
        be.write_stylesheet_block("Demo", "keep", ".stays {}")
        assert be.remove_stylesheet_block("Demo", "never-written") is False
        with pytest.raises(ValueError, match="marker"):
            be.remove_stylesheet_block("Demo", "bad marker!")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
