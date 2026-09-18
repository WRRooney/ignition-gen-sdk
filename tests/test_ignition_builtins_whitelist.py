"""Tests for the Ignition expression-function and system.*-function whitelists
and the three author-time guards wired to them.

Bug class: a reference to a function that does not exist (expression typo, wrong
system namespace, system leaf typo) passes JSON/model/ast validation but throws
at runtime in the gateway. The whitelists catch it at author time.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import pytest

from ignition_gen_sdk.validation import (
    unknown_expression_functions,
    unknown_system_calls,
)

# Corpus tests scan a real gateway data dir READ-ONLY; point IGNITION_CORPUS_DIR at one.
_DATA = Path(os.environ.get("IGNITION_CORPUS_DIR") or "/nonexistent")


# --- expression-function checker ---


def test_known_expression_functions_pass() -> None:
    assert unknown_expression_functions(
        'if({x} = "a", numberFormat({v}, "#0.0"), substringAfterLast({s}, "/"))'
    ) == []


def test_unknown_expression_function_flagged() -> None:
    assert unknown_expression_functions("frobnicate({x})") == ["frobnicate"]


def test_expression_function_names_are_case_insensitive() -> None:
    # Ignition expression function names are case-insensitive (verified vs
    # IA-authored IndustryPack views: COALESCE / isnull / tostr all valid).
    assert unknown_expression_functions("COALESCE({x}, 0)") == []
    assert unknown_expression_functions("isnull({y})") == []
    assert unknown_expression_functions("tostr({z})") == []
    assert unknown_expression_functions("IF({a} = 1, 2, 3)") == []


def test_color_gradient_typeof_recognized() -> None:
    # real IA expression functions surfaced by the IA-corpus stress test
    assert unknown_expression_functions("color(255,0,0)") == []
    assert unknown_expression_functions("gradient({v}, 0, 100, color(0,0,0), color(255,255,255))") == []
    assert unknown_expression_functions("typeOf({x})") == []


def test_expression_literals_and_refs_not_mistaken_for_calls() -> None:
    # a '(' inside a string literal, and a ref name, must not be read as a call
    assert unknown_expression_functions('if({a.b.c} = "weird(value)", 1, 0)') == []


# --- system.* checker ---


def test_valid_system_calls_pass() -> None:
    code = (
        "v = system.tag.readBlocking([p])\n"
        "system.perspective.navigate(page='/x')\n"
        "system.util.getLogger('a').info('b')\n"
    )
    assert unknown_system_calls(code) == []


def test_audit_functions_recognized() -> None:
    # system.util.audit is real in 8.3 (crawled builtins + live round-trip vs
    # the Events audit profile); it was missing from the enforced whitelist
    # while queryAuditLog was present. Project scripts use both.
    code = (
        "system.util.audit(action='Cat', auditProfile='Events')\n"
        "ds = system.util.queryAuditLog(auditProfileName='Events', startDate=s, endDate=e)\n"
    )
    assert unknown_system_calls(code) == []


def test_historian_namespace_recognized() -> None:
    # 8.3 historian API (crawl-verified); used by trend-export scripts.
    code = (
        "a = system.historian.queryAggregatedPoints(p, s, e, g)\n"
        "b = system.historian.queryRawPoints(p, s, e, n)\n"
    )
    assert unknown_system_calls(code) == []


def test_wrong_namespace_flagged_any_subpackage() -> None:
    # 'tags' is not a real namespace (it's 'tag') — caught regardless of leaf list
    assert unknown_system_calls("system.tags.read([p])") == ["system.tags.read"]


def test_unknown_leaf_flagged_in_enforced_namespace() -> None:
    # system.tag is fully sourced -> a leaf typo is caught
    assert unknown_system_calls("system.tag.readBlockng([p])") == ["system.tag.readBlockng"]


def test_unknown_leaf_allowed_in_advisory_namespace() -> None:
    # system.alarm is a valid subpackage but NOT leaf-enforced (leaf list not yet
    # fully sourced) -> an unknown leaf passes; the subpackage is still validated.
    # (Documented behavior, not a defect. perspective/db/util/tag/security ARE
    # leaf-enforced.)
    assert unknown_system_calls("system.alarm.someNewThing(x)") == []


def test_perspective_leaf_typo_caught() -> None:
    # perspective is leaf-enforced — a leaf typo is now caught
    assert unknown_system_calls("system.perspective.navigte(page='/x')") == [
        "system.perspective.navigte"
    ]
    assert unknown_system_calls("system.perspective.navigate(page='/x')") == []


def test_project_script_calls_ignored() -> None:
    assert unknown_system_calls("tree = app.nav.buildNavTree()\nshared.util.doThing()") == []


def test_system_in_string_literal_ignored() -> None:
    assert unknown_system_calls('msg = "call system.bogus.thing manually"') == []


# --- wired guards ---


def test_bind_expression_rejects_unknown_function() -> None:
    from ignition_gen_sdk.models.views.component import Component, ExpressionSyntaxError

    c = Component(type="ia.display.label")
    with pytest.raises(ExpressionSyntaxError):
        c.bind_expression("props.text", "frobnicate({view.custom.x})")


def test_add_event_rejects_unknown_system_call() -> None:
    from ignition_gen_sdk.models.views.component import Component, ExpressionSyntaxError
    from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig

    c = Component(type="ia.input.button")
    handler = ScriptEventHandler(
        type="script", scope="G",
        config=ScriptEventConfig(script="system.tags.write([p],[v])"),  # wrong namespace
    )
    with pytest.raises(ExpressionSyntaxError):
        c.add_event("component", "onActionPerformed", handler)


def test_add_event_accepts_valid_system_call() -> None:
    from ignition_gen_sdk.models.views.component import Component
    from ignition_gen_sdk.models.views.events import ScriptEventHandler, ScriptEventConfig

    c = Component(type="ia.input.button")
    handler = ScriptEventHandler(
        type="script", scope="G",
        config=ScriptEventConfig(script="system.perspective.navigate(page='/x')"),
    )
    c.add_event("component", "onActionPerformed", handler)  # no raise


# --- project sweep: every expression + script in the data dir passes ---


def _iter_view_files() -> list[str]:
    files = glob.glob(
        str(_DATA / "projects/Demo/com.inductiveautomation.perspective/views/**/view.json"),
        recursive=True,
    )
    return files


def test_all_framework_expressions_are_whitelisted() -> None:
    bad = []
    for vf in _iter_view_files():
        view = json.loads(Path(vf).read_text(encoding="utf-8"))

        def walk(o):
            if isinstance(o, dict):
                if o.get("type") == "expr" and isinstance(o.get("config"), dict):
                    e = o["config"].get("expression")
                    if isinstance(e, str):
                        for f in unknown_expression_functions(e):
                            bad.append((vf, f, e[:60]))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)

        walk(view)
    assert not bad, f"framework expressions use non-whitelisted functions: {bad}"


def _reference_corpus_roots() -> list[Path]:
    """IA-authored reference projects + sample — the corpus that hardened the
    whitelists. Present on a gateway data dir; may be absent elsewhere."""
    candidates = [
        _DATA / "projects" / "IndustryPack-Water",
        _DATA / "projects" / "IndustryPack-DataCenter",
        _DATA / "projects" / "samplequickstart",
    ]
    return [c for c in candidates if c.exists()]


def test_whitelists_have_no_false_positives_on_ia_corpus() -> None:
    """Regression lock: the whitelists must flag ZERO functions/system-calls
    in the IA professional-authored corpus. This guards against re-narrowing the
    whitelist (e.g. re-breaking case-insensitivity, or dropping a real function) —
    the corpus is the authoritative real-world ground truth. Skips if the
    reference projects are not present (portability)."""
    roots = _reference_corpus_roots()
    if not roots:
        pytest.skip("IA reference corpus not present")
    expr_bad: list = []
    sys_bad: list = []
    nfiles = 0
    for root in roots:
        for vf in root.rglob("view.json"):
            nfiles += 1
            try:
                view = json.loads(vf.read_text(encoding="utf-8"))
            except Exception:
                continue

            def walk(o):
                if isinstance(o, dict):
                    if o.get("type") == "expr" and isinstance(o.get("config"), dict):
                        e = o["config"].get("expression")
                        if isinstance(e, str):
                            for f in unknown_expression_functions(e):
                                expr_bad.append((str(vf.name), f, e[:50]))
                    s = o.get("script")
                    if isinstance(s, str):
                        for c in unknown_system_calls(s):
                            sys_bad.append((str(vf.name), c))
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)

            walk(view)
        for sf in root.rglob("code.py"):
            nfiles += 1
            for c in unknown_system_calls(sf.read_text(encoding="utf-8")):
                sys_bad.append((str(sf.name), c))
    assert nfiles > 0
    assert not expr_bad, f"whitelist false-positives on IA expressions: {expr_bad}"
    assert not sys_bad, f"whitelist false-positives on IA system calls: {sys_bad}"


def test_all_framework_system_calls_are_whitelisted() -> None:
    bad = []
    for vf in _iter_view_files():
        view = json.loads(Path(vf).read_text(encoding="utf-8"))

        def walk(o):
            if isinstance(o, dict):
                s = o.get("script")
                if isinstance(s, str):
                    for c in unknown_system_calls(s):
                        bad.append((vf, c))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)

        walk(view)
    for sf in glob.glob(
        str(_DATA / "projects/Demo/ignition/script-python/**/code.py"), recursive=True
    ):
        for c in unknown_system_calls(Path(sf).read_text(encoding="utf-8")):
            bad.append((sf, c))
    # Project scripts use 8.3 system.tag.browse, not the 7.x-dead
    # system.tag.browseTags; browseTags stays OUT of the whitelist (it IS broken).
    assert not bad, f"framework scripts call non-whitelisted system.* functions: {bad}"
