"""Lock the package public API.

`ignition_gen_sdk/__init__.py` previously exported only __version__, forcing
callers to hunt deep module paths. The most-used symbols are now re-exported at
the top level; this test locks them (and that they're the same objects as the
deep import).
"""
from __future__ import annotations


def test_top_level_exports_present():
    import ignition_gen_sdk as ig
    for name in ("ViewBuilder", "Tag", "Alarm", "Component", "ProjectDiskBackend", "__version__"):
        assert name in ig.__all__, f"{name} missing from __all__"
        assert hasattr(ig, name), f"{name} not importable from package root"


def test_exports_are_the_canonical_objects():
    from ignition_gen_sdk import ViewBuilder, Tag, ProjectDiskBackend
    from ignition_gen_sdk.builders.view import ViewBuilder as DeepVB
    from ignition_gen_sdk.models.tags.tag import Tag as DeepTag
    from ignition_gen_sdk.backends.project_disk import ProjectDiskBackend as DeepBackend

    assert ViewBuilder is DeepVB
    assert Tag is DeepTag
    assert ProjectDiskBackend is DeepBackend
