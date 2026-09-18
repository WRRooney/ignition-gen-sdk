"""page mount --dock: spec parsing, dock placement, and the preserve-on-remount
rule (re-mounting a URL must never silently drop its docked chrome)."""
from __future__ import annotations

import pytest

from ignition_gen_sdk.cli.cmd_page import _docks_from_specs, _parse_dock
from ignition_gen_sdk.models.page_config import PageConfig

HEADER = {"top": [{"anchor": "fixed", "autoBreakpoint": 480, "content": "push",
                   "handle": "hide", "iconUrl": "", "id": "header", "modal": False,
                   "resizable": False, "show": "visible", "size": 48,
                   "viewParams": {}, "viewPath": "Navigation/Header"}]}


def test_parse_dock_defaults_size_per_side():
    side, entry = _parse_dock("top:Navigation/Header")
    assert side == "top" and entry["size"] == 48
    assert entry["viewPath"] == "Navigation/Header" and entry["id"] == "header"
    assert _parse_dock("left:Nav/Side")[1]["size"] == 260
    assert _parse_dock("right:Nav/Side")[1]["size"] == 300
    assert _parse_dock("top:Nav/H:64")[1]["size"] == 64


@pytest.mark.parametrize("spec", ["Navigation/Header", "middle:X", "top:", "top:X:big"])
def test_parse_dock_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        _parse_dock(spec)


def test_docks_from_specs_groups_by_side():
    docks = _docks_from_specs(["top:Nav/Header", "left:Nav/Tree", "left:Nav/Tree2"])
    assert set(docks) == {"top", "left"} and len(docks["left"]) == 2
    assert _docks_from_specs(None) is None


def test_with_page_preserves_existing_docks_when_none_passed():
    cfg = PageConfig().with_page("/", "Nav/Main", "Home", docks=HEADER)
    again = cfg.with_page("/", "Nav/Other")  # a plain re-mount
    assert again.config_json()["pages"]["/"]["docks"] == HEADER
    assert again.pages["/"].viewPath == "Nav/Other"


def test_with_page_replaces_and_clears_docks():
    cfg = PageConfig().with_page("/", "Nav/Main", docks=HEADER)
    assert cfg.with_page("/", "Nav/Main", docks={}).config_json()["pages"]["/"]["docks"] == {}
    other = _docks_from_specs(["bottom:Nav/Foot"])
    assert cfg.with_page("/", "Nav/Main", docks=other).pages["/"].model_dump()["docks"] == other

def test_shared_docks_replace_only_the_named_side():
    """`page shared-dock` writes project-wide chrome: the phone footer must not
    be able to drop the header, and cornerPriority must survive both."""
    cfg = PageConfig().with_page("/", "Nav/Main").with_shared_docks(HEADER)
    both = cfg.with_shared_docks(_docks_from_specs(["bottom:Navigation/FooterMobile:56"]))
    shared = both.config_json()["sharedDocks"]
    assert shared["top"] == HEADER["top"]
    assert shared["bottom"][0]["viewPath"] == "Navigation/FooterMobile"
    assert shared["bottom"][0]["size"] == 56
    assert shared["cornerPriority"] == "top-bottom"
    assert both.pages["/"].viewPath == "Nav/Main"  # pages untouched


def test_without_shared_dock_removes_one_side_only():
    cfg = PageConfig().with_shared_docks(HEADER).with_shared_docks(
        _docks_from_specs(["bottom:Nav/Foot"]))
    left = cfg.without_shared_dock("bottom").config_json()["sharedDocks"]
    assert set(left) == {"cornerPriority", "top"}
    # removing a side that was never set is a no-op, not a KeyError
    assert cfg.without_shared_dock("left").sharedDocks == cfg.sharedDocks


def test_delete_page_config_makes_a_child_inherit():
    """A child holding ANY page-config overrides the parent's outright, so
    deleting the resource is the only way to fall back to inherited routes."""
    import tempfile
    from pathlib import Path as _P

    from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend

    class _S:
        def __init__(self, root):
            self.ignition_data_root = root

    with tempfile.TemporaryDirectory() as d:
        root = _P(d)
        proj = root / "projects" / "Child"
        proj.mkdir(parents=True)
        (proj / "project.json").write_text("{}")
        be = ProjectDiskBackend(_S(root))  # type: ignore[arg-type]

        cfg = PageConfig().with_page("/", "Nav/Main", docks=HEADER)
        dest = be.write_page_config("Child", cfg)
        assert (dest / "config.json").is_file()

        removed = be.delete_page_config("Child")
        assert not removed.exists()
        assert be.read_page_config("Child").pages == {}  # now inherits

        with pytest.raises(FileNotFoundError, match="no page-config"):
            be.delete_page_config("Child")
if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
