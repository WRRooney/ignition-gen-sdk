"""Tests for view serializers."""
from __future__ import annotations


from ignition_gen_sdk.models.views.containers import FlexContainer
from ignition_gen_sdk.models.views.meta import Meta
from ignition_gen_sdk.models.views.view import View
from ignition_gen_sdk.serializers.resource_metadata import view_resource_json
from ignition_gen_sdk.serializers.view_disk import view_to_disk


def test_view_resource_json_shape():
    """Verified live shape from samplequickstart resource.json.

    files = ["view.json"] ONLY. An earlier revision pre-listed
    thumbnail.png to match samplequickstart, but the gateway log sweep
    proved a manifest listing a file ign never writes throws
    NoSuchFileException + logs an ERROR on every scan. The thumbnail is
    optional (Designer adds it on first open), so it is omitted.

    Attributes carries lastModification.actor =
    "ign" as an audit-trail marker. Signature still cannot be
    fabricated and is omitted (Designer rewrites on first save).
    """
    r = view_resource_json()
    assert r["scope"] == "G"
    assert r["version"] == 1
    assert r["restricted"] is False
    assert r["overridable"] is True
    # ONLY view.json — no thumbnail.png (avoids the recurring gateway error).
    assert r["files"] == ["view.json"]
    assert "thumbnail.png" not in r["files"]
    # Actor stamp present, signature still NOT fabricated.
    assert r["attributes"]["lastModification"]["actor"] == "ign"
    assert "timestamp" in r["attributes"]["lastModification"]
    assert "lastModificationSignature" not in r["attributes"]


def test_view_resource_json_returns_fresh_dict():
    """Mutating one returned dict must not pollute subsequent calls.

    The attributes dict now has structure, but
    each call constructs a fresh outer dict so mutation is isolated.
    """
    a = view_resource_json()
    a["attributes"] = {"foo": "bar"}
    b = view_resource_json()
    # Default attributes is no longer {} — it carries the actor stamp.
    assert "lastModification" in b["attributes"]
    assert b["attributes"]["lastModification"]["actor"] == "ign"


def test_view_to_disk_minimal_flex():
    v = View(root=FlexContainer(
        meta=Meta(name="root"),
        props={"direction": "column"},
        children=[],
    ))
    out = view_to_disk(v)
    assert out["root"]["type"] == "ia.container.flex"
    assert out["root"]["props"] == {"direction": "column"}
    # Empty children is OMITTED from the emit shape
    # to match every observed gateway sample (no sample emits an empty
    # children list at the component level).
    assert "children" not in out["root"]
    # View-level keys are preserved (only Component-level empties
    # are stripped). Home Large/view.json shows "custom": {} at root.
    assert "params" in out and "custom" in out and "props" in out


def test_view_resource_json_documentation_after_scope_and_designer_dumps_literal_unicode():
    """`--doc-file` → resource.json `documentation` right after `scope` (Designer
    order); absent when not given. dumps_designer keeps non-ASCII literal (Gson
    policy) — the escaped form churned every `m³` line."""
    from ignition_gen_sdk.backends.project_disk import dumps_designer
    r = view_resource_json("MIT License")
    assert list(r)[:2] == ["scope", "documentation"] and r["documentation"] == "MIT License"
    assert "documentation" not in view_resource_json()
    assert dumps_designer({"a": "m³ x=1"}) == '{\n  "a": "m³ x\\u003d1"\n}'
