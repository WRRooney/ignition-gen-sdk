"""base model, settings, enums.

Behavior contracts:
- IgnitionBaseModel rejects credential JWE fields with ValueError.
- TagDataType.DOUBLE.value == "Float8".
- TagAlarmMode.WHEN_TRUE.value == "WhenTrue", WHEN_FALSE.value == "WhenFalse".
- Settings repr does NOT contain raw token, only [REDACTED].
- IgnitionBaseModel.emit() omits None values.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _add_pkg_path() -> None:
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


class TestIgnitionBaseModel(unittest.TestCase):
    def test_credential_guard_blocks_ciphertext(self) -> None:
        from ignition_gen_sdk.models.base import IgnitionBaseModel

        with self.assertRaises(ValueError) as cm:
            IgnitionBaseModel.model_validate({"ciphertext": "x"})
        msg = str(cm.exception).lower()
        self.assertTrue("forbidden" in msg or "encrypted" in msg)

    def test_credential_guard_blocks_each_jwe_field(self) -> None:
        from ignition_gen_sdk.models.base import IgnitionBaseModel

        for field in ("ciphertext", "encrypted_key", "iv", "protected", "tag"):
            with self.assertRaises(ValueError, msg=f"{field} not blocked"):
                IgnitionBaseModel.model_validate({field: "x"})

    def test_emit_drops_none(self) -> None:
        # Use a small Pydantic subclass so we can exercise emit() with optionals.
        from typing import Optional

        from ignition_gen_sdk.models.base import IgnitionBaseModel

        class _M(IgnitionBaseModel):
            a: int
            b: Optional[str] = None

        out = _M(a=1).emit()
        self.assertEqual(out, {"a": 1})
        self.assertNotIn("b", out)


class TestEnums(unittest.TestCase):
    def test_tag_datatype_double_is_float8(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType

        self.assertEqual(TagDataType.DOUBLE.value, "Float8")
        self.assertEqual(TagDataType.FLOAT.value, "Float4")
        self.assertEqual(TagDataType.INTEGER.value, "Int4")

    def test_tag_alarm_mode_8_3_members(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_alarm_mode import TagAlarmMode

        self.assertEqual(TagAlarmMode.WHEN_TRUE.value, "WhenTrue")
        self.assertEqual(TagAlarmMode.WHEN_FALSE.value, "WhenFalse")
        # Existing values still present
        self.assertEqual(TagAlarmMode.ABOVE_SETPOINT.value, "AboveValue")

    def test_tag_type_atomic(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType

        self.assertEqual(TagType.ATOMIC.value, "AtomicTag")
        self.assertEqual(TagType.PROVIDER.value, "Provider")

    def test_tag_value_source(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource

        self.assertEqual(TagValueSource.OPC.value, "opc")
        self.assertEqual(TagValueSource.MEMORY.value, "memory")

    def test_tag_alarm_priority(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_alarm_priority import TagAlarmPriority

        self.assertEqual(TagAlarmPriority.CRITICAL.value, "Critical")
        self.assertEqual(TagAlarmPriority.LOW.value, "Low")

    def test_tag_scale_mode(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_scale_mode import TagScaleMode

        self.assertEqual(TagScaleMode.LINEAR.value, "Linear")
        self.assertEqual(TagScaleMode.OFF.value, "Off")


class TestSettings(unittest.TestCase):
    def test_repr_redacts_token(self) -> None:
        # Provide token via env so we don't depend on .env file resolution.
        with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:test-secret-token-DO-NOT-LEAK"}, clear=False):
            from ignition_gen_sdk.config import Settings

            s = Settings()
            r = repr(s)
            self.assertIn("REDACTED", r)
            self.assertNotIn("test-secret-token-DO-NOT-LEAK", r)
            self.assertNotIn("test-secret-token-DO-NOT-LEAK", str(s))


if __name__ == "__main__":
    unittest.main()
