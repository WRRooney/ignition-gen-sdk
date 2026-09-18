"""Tests for the runScript() performance warning.

`runScript(...)` in an expression executes Jython on every evaluation — it
carries SCRIPT-tier cost (per PERFORMANCE_ORDER), not cheap-expression cost. The
author-time expression gate (_check_expression_syntax, shared by bind_expression,
.expression() transform, bind_expression_structure, bind_custom_expression)
emits a non-fatal BindingPerformanceWarning so the smell is visible, without
blocking (runScript is sometimes the only option).

Test IDs:
  - test_runscript_expression_warns
  - test_plain_expression_no_warn
  - test_runscript_in_string_literal_no_warn
  - test_runscript_warning_via_transform_chain
  - test_warning_is_non_fatal_binding_still_attached
"""
from __future__ import annotations

import warnings
import unittest

from ignition_gen_sdk.builders.view import ViewBuilder
from ignition_gen_sdk.models.views.component import BindingPerformanceWarning


def _warns(expr: str) -> bool:
    vb = ViewBuilder()
    vb.flex_root()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        vb.label(text="x").bind_expression("text", expr)
    return any(issubclass(x.category, BindingPerformanceWarning) for x in w)


class TestRunScriptPerfWarning(unittest.TestCase):
    def test_runscript_expression_warns(self):
        self.assertTrue(_warns('runScript("pkg.mod.fn()")'))

    def test_runscript_case_insensitive_warns(self):
        # Ignition expression function names are case-insensitive.
        self.assertTrue(_warns('RunScript("pkg.mod.fn()")'))

    def test_plain_expression_no_warn(self):
        self.assertFalse(_warns('upper({view.params.name})'))

    def test_runscript_in_string_literal_no_warn(self):
        # A runScript token inside a quoted literal is not a call → no warning.
        self.assertFalse(_warns('upper("mentions runScript() in text") + {view.params.n}'))

    def test_runscript_warning_via_transform_chain(self):
        # The .expression() transform helper shares the same gate.
        vb = ViewBuilder()
        vb.flex_root()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            (vb.label(text="x")
               .bind_text("[default]Some/Tag")
               .expression('runScript("pkg.mod.fn()")'))
        self.assertTrue(any(issubclass(x.category, BindingPerformanceWarning) for x in w))

    def test_warning_is_non_fatal_binding_still_attached(self):
        vb = ViewBuilder()
        vb.flex_root()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lbl = vb.label(text="x").bind_expression("text", 'runScript("pkg.mod.fn()")')
        # Binding still attached despite the warning.
        assert any(pc.prop == "text" for pc in lbl.propConfig), "expression binding must still attach"


if __name__ == "__main__":
    unittest.main()
