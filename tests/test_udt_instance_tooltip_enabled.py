"""UdtInstance must accept `tooltip` and `enabled`.

Both are ordinary Ignition tag properties an instance can set independently of
its type, and `enabled` is load-bearing for UDT-driven view discovery: field,
summary and nav discovery all filter on the tag's `.enabled` config property, so the
"disabled in the type, switched on per instance" convention cannot be written
at all without it. The model previously rejected both as unknown fields.
"""
from __future__ import annotations

import unittest


class TestUdtInstanceProperties(unittest.TestCase):
    def test_tooltip_and_enabled_round_trip(self):
        from ignition_gen_sdk.models.tags.udt import UdtInstance

        inst = UdtInstance.model_validate({
            "name": "Default",
            "tagType": "UdtInstance",
            "typeId": "Alarm/RosterConfig",
            "tooltip": "Default on-call roster.",
            "enabled": False,
        })
        self.assertEqual(inst.tooltip, "Default on-call roster.")
        self.assertIs(inst.enabled, False)
        out = inst.model_dump(exclude_none=True, mode="json")
        self.assertEqual(out["tooltip"], "Default on-call roster.")
        self.assertIs(out["enabled"], False)

    def test_omitted_properties_are_not_emitted(self):
        from ignition_gen_sdk.models.tags.udt import UdtInstance

        inst = UdtInstance.model_validate({
            "name": "Plain", "tagType": "UdtInstance", "typeId": "Alarm/RosterConfig",
        })
        out = inst.model_dump(exclude_none=True, mode="json")
        self.assertNotIn("tooltip", out)
        self.assertNotIn("enabled", out)

    def test_unknown_non_meta_field_is_still_rejected(self):
        from ignition_gen_sdk.models.tags.udt import UdtInstance

        with self.assertRaises(ValueError):
            UdtInstance.model_validate({
                "name": "Bad", "tagType": "UdtInstance",
                "typeId": "Alarm/RosterConfig", "toolTip": "typo",
            })


if __name__ == "__main__":
    unittest.main()
