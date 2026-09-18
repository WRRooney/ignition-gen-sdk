"""Tests for input palette component models — NumericEntryField type string.

NumericEntryField.type must be "ia.input.numeric-entry-field": every live
Designer-authored view uses it; the literal "ia.input.numericEntry" appears in
zero live views.
"""
from __future__ import annotations





CORRECT_TYPE = "ia.input.numeric-entry-field"
OLD_TYPE = "ia.input.numericEntry"


def test_numeric_entry_field_type_string():
    """NumericEntryField().type must equal the real Ignition type string."""
    from ignition_gen_sdk.models.views.components.input import NumericEntryField

    assert NumericEntryField().type == CORRECT_TYPE


def test_numeric_entry_field_type_not_old_string():
    """NumericEntryField().type must NOT be the old wrong literal."""
    from ignition_gen_sdk.models.views.components.input import NumericEntryField

    assert NumericEntryField().type != OLD_TYPE


def test_numeric_entry_field_no_old_string_in_dump():
    """Old type string must not appear in model_dump_json output."""
    from ignition_gen_sdk.models.views.components.input import NumericEntryField

    dumped = NumericEntryField().model_dump_json()
    assert OLD_TYPE not in dumped
