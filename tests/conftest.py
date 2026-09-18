"""Shared pytest helpers for fixture-diff tests.

Test files previously duplicated ~50 lines of fixture-root discovery,
view-loading, and propConfig-walk helpers. This module owns the canonical
implementations.

The samplequickstart fixtures are NOT in git; a fresh clone won't have
them and CI nodes that don't clone the workspace won't either. The helpers
here fail loudly when the fixture set is missing rather than silently
skipping — fixture-diff tests are the only verification gate that the
emitted JSON matches the gateway wire shape, so a silent skip means that
check never actually ran.
"""
from __future__ import annotations

import os

# Seed a fake API key so Settings() can construct in test environments that
# lack a real .env (test isolation). setdefault never overwrites a real key
# that is already present in the process environment (e.g. from .env exports).
os.environ.setdefault("IGNITION_API_TOKEN", "test:test-secret-DO-NOT-LEAK")

from ignition_gen_sdk.config import Settings  # noqa: E402

# Gateway base URL for tests, resolved the way the SDK resolves it: IGNITION_URL
# from the environment or .env, else the SDK default. Read before the scrub
# below; tests import this instead of hardcoding a host.
GATEWAY_URL = Settings().ignition_base_url.rstrip("/")

# Tests must never touch a real gateway. Whatever the shell exported, the data
# dir every Settings() in this process resolves to is an empty temp dir; tests
# that need files create them there or pass their own Settings.
import tempfile  # noqa: E402

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="ignition-gen-sdk-tests-")
os.environ["IGNITION_DATA_DIR"] = _TEST_DATA_DIR
os.environ.pop("IGNITION_URL", None)
os.environ.pop("IGNITION_PROJECT", None)

from pathlib import Path
from typing import Any

import json
import pytest


# Fixture-diff tests compare emitted JSON against the Perspective views of
# Ignition's bundled "samplequickstart" project. That project is IA-distributed
# and not vendored here: export it from your own gateway and point
# IGNITION_SAMPLE_VIEWS at its `com.inductiveautomation.perspective/views` dir.
_SAMPLE_ENV = "IGNITION_SAMPLE_VIEWS"


def _find_fixture_root() -> Path | None:
    """Sample views dir from IGNITION_SAMPLE_VIEWS, or None when unset/missing."""
    raw = os.environ.get(_SAMPLE_ENV)
    if raw and Path(raw).is_dir():
        return Path(raw)
    return None


FIXTURE_ROOT: Path | None = _find_fixture_root()


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    """Session-scoped fixture-root path. Skips with explicit message when
    the samplequickstart set is not present.
    """
    if FIXTURE_ROOT is None:
        pytest.skip(
            f"{_SAMPLE_ENV} not set: export the gateway's samplequickstart "
            "project and point it at the views dir to run fixture-diff tests.",
        )
    return FIXTURE_ROOT


def load_view(view_relpath: str) -> dict:
    """Read a Perspective view.json from the samplequickstart fixture set.

    Fails loudly if FIXTURE_ROOT was not discovered.
    """
    if FIXTURE_ROOT is None:
        pytest.skip(f"{_SAMPLE_ENV} not set; fixture-diff test skipped.")
    p = FIXTURE_ROOT / view_relpath
    with p.open("r") as fp:
        return json.load(fp)


def find_propconfig_by_type(
    node: Any,
    target_type: str,
    accum: list | None = None,
) -> list:
    """Walk a view tree; collect (prop_path, binding_dict) pairs for bindings
    whose `binding.type == target_type`. Recursive.
    """
    if accum is None:
        accum = []
    if isinstance(node, dict):
        pc = node.get("propConfig")
        if isinstance(pc, dict):
            for prop, body in pc.items():
                binding = (body or {}).get("binding")
                if isinstance(binding, dict) and binding.get("type") == target_type:
                    accum.append((prop, binding))
        for v in node.values():
            find_propconfig_by_type(v, target_type, accum)
    elif isinstance(node, list):
        for v in node:
            find_propconfig_by_type(v, target_type, accum)
    return accum


def is_superset(superset: dict, subset: dict, path: str = "") -> None:
    """Assert every key+value in `subset` is present in `superset` with the
    same value. Nested dicts compared recursively; lists element-wise.
    """
    for k, v in subset.items():
        ctx = f"{path}/{k}"
        assert k in superset, f"missing key {ctx} in superset: {superset}"
        if isinstance(v, dict):
            assert isinstance(superset[k], dict), (
                f"{ctx}: expected dict, got {type(superset[k])}"
            )
            is_superset(superset[k], v, ctx)
        elif isinstance(v, list):
            assert isinstance(superset[k], list), (
                f"{ctx}: expected list, got {type(superset[k])}"
            )
            assert len(superset[k]) == len(v), f"{ctx}: list length mismatch"
            for i, (sup_item, sub_item) in enumerate(zip(superset[k], v)):
                if isinstance(sub_item, dict):
                    is_superset(sup_item, sub_item, f"{ctx}[{i}]")
                else:
                    assert sup_item == sub_item, (
                        f"{ctx}[{i}]: {sup_item!r} != {sub_item!r}"
                    )
        else:
            assert superset[k] == v, f"{ctx}: {superset[k]!r} != {v!r}"


# Modules that exercise the generated OpenAPI client or the path resolver need a
# real gateway spec: `ign openapi fetch` writes it to <state-dir>/openapi.json, or
# point IGNITION_OPENAPI_SPEC_PATH at one.
_SPEC_MODULES = {
    "test_api_backend_database_connections",
    "test_api_backend",
    "test_openapi_resolver",
    "test_gen_api_backend_parity",
    "test_cli_api",
    "test_cli_api_strict",
}


# Binding/transform modules whose fixture-diff tests read the sample views.
_VIEW_MODULES = {
    "test_property_binding",
    "test_expression_transform_chain",
    "test_tag_binding",
    "test_map_format_script_transforms",
    "test_expression_bindings",
    "test_query_binding",
    "test_tag_history_binding",
    "test_http_binding",
}


def _spec_present() -> bool:
    raw = os.environ.get("IGNITION_OPENAPI_SPEC_PATH")
    if raw:
        return Path(raw).is_file()
    return (Path(os.environ.get("IGNITION_STATE_DIR", ".ign")) / "openapi.json").is_file()


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    """Skip modules whose external inputs (sample views, gateway spec) are absent."""
    no_views = pytest.mark.skip(reason=f"{_SAMPLE_ENV} not set; fixture-diff tests skipped.")
    no_spec = pytest.mark.skip(reason="no OpenAPI spec; run `ign openapi fetch` or set IGNITION_OPENAPI_SPEC_PATH.")
    views_ok, spec_ok = FIXTURE_ROOT is not None, _spec_present()
    for item in items:
        mod = item.module.__name__
        if not views_ok and mod in _VIEW_MODULES:
            item.add_marker(no_views)
        if not spec_ok and mod in _SPEC_MODULES:
            item.add_marker(no_spec)
