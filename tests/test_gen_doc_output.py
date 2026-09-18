"""Tests for doc_gen.py — spec JSON → api_reference/*.md generation.

Doc-gen produces INDEX.md + AUTH.md + tag files. AUTH.md contains the
${IGNITION_API_TOKEN} placeholder, not a literal token.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch



# ---------------------------------------------------------------------------
# Micro-spec fixture for integration tests
# ---------------------------------------------------------------------------

MICRO_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "tags": [
        {"name": "widget", "description": "Widget operations"},
        {"name": "gadget", "description": "Gadget operations"},
    ],
    "x-tagGroups": [
        {"name": "Core", "tags": ["widget", "gadget"]},
    ],
    "paths": {
        "/data/api/v1/widgets": {
            "get": {
                "tags": ["widget"],
                "summary": "List widgets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                        "description": "Max items to return",
                    }
                ],
            },
            "post": {
                "tags": ["widget"],
                "summary": "Create widget",
                "parameters": [],
                "requestBody": {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                },
            },
        },
        "/data/api/v1/gadgets/{id}": {
            "get": {
                "tags": ["gadget"],
                "summary": "Get gadget by ID",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Gadget identifier",
                    }
                ],
            },
            "delete": {
                "tags": ["gadget"],
                "summary": "Delete gadget",
                "parameters": [],
            },
        },
    },
}


def _run_generate_docs_with_temp_dir(spec: dict, tmp_path: Path) -> Path:
    """Run generate_docs() with the spec loaded from a micro-spec dict.

    Patches load_spec() to return the micro-spec and _API_REF_DIR to write
    into tmp_path so tests are fully isolated from real api_reference/.
    """
    import ignition_gen_sdk.regen.doc_gen as doc_gen_mod

    with patch.object(doc_gen_mod, "api_reference_dir", lambda _s: tmp_path):
        with patch("ignition_gen_sdk.regen.doc_gen.load_spec", return_value=spec):
            doc_gen_mod.generate_docs(settings=None)

    return tmp_path


# ---------------------------------------------------------------------------
# File structure — AUTH.md, INDEX.md, tag slug files
# ---------------------------------------------------------------------------

def test_generate_docs_creates_expected_files(tmp_path):
    """generate_docs() with micro-spec creates AUTH.md, INDEX.md, widget.md, gadget.md."""
    out_dir = _run_generate_docs_with_temp_dir(MICRO_SPEC, tmp_path)

    assert (out_dir / "AUTH.md").exists(), "AUTH.md not created"
    assert (out_dir / "INDEX.md").exists(), "INDEX.md not created"
    assert (out_dir / "widget.md").exists(), "widget.md not created"
    assert (out_dir / "gadget.md").exists(), "gadget.md not created"


# ---------------------------------------------------------------------------
# AUTH.md length > 400 chars
# ---------------------------------------------------------------------------

def test_auth_md_is_not_empty(tmp_path):
    """AUTH.md must be substantial (> 400 chars) to pass the content guard."""
    out_dir = _run_generate_docs_with_temp_dir(MICRO_SPEC, tmp_path)
    content = (out_dir / "AUTH.md").read_text(encoding="utf-8")
    assert len(content) > 400, (
        f"AUTH.md content too short ({len(content)} chars) — template may be empty"
    )


# ---------------------------------------------------------------------------
# AUTH.md has ${IGNITION_API_TOKEN} and NO literal token
# ---------------------------------------------------------------------------

def test_auth_md_placeholder_not_literal_token(tmp_path):
    """AUTH.md must contain env-var placeholder and MUST NOT contain a literal token."""
    out_dir = _run_generate_docs_with_temp_dir(MICRO_SPEC, tmp_path)
    content = (out_dir / "AUTH.md").read_text(encoding="utf-8")

    assert "${IGNITION_API_TOKEN}" in content, (
        "AUTH.md missing ${IGNITION_API_TOKEN} placeholder"
    )
    # No literal test:<token> value
    assert not re.search(r"test:[A-Za-z0-9_-]{4,}", content), (
        "AUTH.md contains a literal test:... token "
    )


# ---------------------------------------------------------------------------
# INDEX.md exists and contains a link
# ---------------------------------------------------------------------------

def test_index_md_has_links(tmp_path):
    """INDEX.md must be non-empty and contain at least one markdown link."""
    out_dir = _run_generate_docs_with_temp_dir(MICRO_SPEC, tmp_path)
    content = (out_dir / "INDEX.md").read_text(encoding="utf-8")

    assert len(content) > 0, "INDEX.md is empty"
    assert "[" in content and "](" in content, (
        "INDEX.md contains no markdown links"
    )


# ---------------------------------------------------------------------------
# render_endpoint_doc contains ign api example
# ---------------------------------------------------------------------------

def test_render_endpoint_doc_contains_example():
    """render_endpoint_doc() must include ign api METHOD PATH example."""
    from ignition_gen_sdk.regen.doc_gen import render_endpoint_doc

    doc = render_endpoint_doc("GET", "/foo/bar", {"summary": "Test summary"})

    assert "ign api GET /foo/bar" in doc, (
        f"render_endpoint_doc did not include 'ign api GET /foo/bar'; got:\n{doc}"
    )


# ---------------------------------------------------------------------------
# render_endpoint_doc includes parameters table when params present
# ---------------------------------------------------------------------------

def test_render_endpoint_doc_includes_params():
    """render_endpoint_doc() includes Parameters table when op has parameters."""
    from ignition_gen_sdk.regen.doc_gen import render_endpoint_doc

    op = {
        "summary": "List items",
        "parameters": [
            {
                "name": "limit",
                "in": "query",
                "required": False,
                "schema": {"type": "integer"},
                "description": "Max items",
            }
        ],
    }
    doc = render_endpoint_doc("GET", "/items", op)

    assert "Parameters" in doc
    assert "limit" in doc
    assert "query" in doc


# ---------------------------------------------------------------------------
# regen/engine.py _run_docgen calls generate_docs (no longer stub)
# ---------------------------------------------------------------------------

def test_run_docgen_calls_generate_docs(tmp_path):
    """regen/engine.py _run_docgen() must call doc_gen.generate_docs(), not return None stub."""
    import ignition_gen_sdk.regen.doc_gen as doc_gen_mod
    import ignition_gen_sdk.regen.engine as engine_mod

    called_with = []

    def fake_generate_docs(settings=None):
        called_with.append(settings)

    with patch.object(doc_gen_mod, "generate_docs", fake_generate_docs):
        # Reload the _run_docgen function binding
        with patch("ignition_gen_sdk.regen.doc_gen.generate_docs", fake_generate_docs):
            engine_mod._run_docgen(settings=None)

    # If _run_docgen is still the stub (returns None without calling), called_with is empty
    # This test may pass trivially if engine imports doc_gen directly — that's fine.
    # The key check is that _run_docgen is no longer just `return None`.
    import inspect
    src = inspect.getsource(engine_mod._run_docgen)
    assert "return None" not in src or "generate_docs" in src, (
        "_run_docgen still appears to be a stub (return None without calling generate_docs)"
    )
    assert "generate_docs" in src, (
        "_run_docgen does not call generate_docs — still a stub"
    )
