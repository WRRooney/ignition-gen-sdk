"""Tests for ViewBuilder.custom() + bind_custom_tag().

The builder doctrine requires tag data to live on view.custom.*, but the builder had no
public way to express that. These lock the new public helpers.
"""
from __future__ import annotations

import unittest


class TestViewCustomBinding(unittest.TestCase):
    def _build(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        from ignition_gen_sdk.serializers.view_disk import view_to_disk
        vb = ViewBuilder()
        vb.coord_root()
        vb.bind_custom_tag("waterTankLevel", "[default]Loop/T01/WaterTankLevel")
        lbl = vb.label(text="", name="LevelLabel")
        lbl.bind_property("props.text", "view.custom.waterTankLevel")
        return view_to_disk(vb.build())

    def test_custom_property_registered(self):
        out = self._build()
        self.assertIn("waterTankLevel", out["custom"])

    def test_view_level_tag_binding_emitted(self):
        out = self._build()
        binding = out["propConfig"]["custom.waterTankLevel"]["binding"]
        self.assertEqual(binding["type"], "tag")
        self.assertEqual(binding["config"]["tagPath"], "[default]Loop/T01/WaterTankLevel")
        self.assertEqual(binding["config"]["mode"], "direct")

    def test_custom_setter_default_value(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        vb = ViewBuilder()
        vb.flex_root()
        vb.custom("threshold", 75)
        self.assertEqual(vb.build().custom["threshold"], 75)

    def test_bind_custom_tag_bidirectional(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        from ignition_gen_sdk.serializers.view_disk import view_to_disk
        vb = ViewBuilder()
        vb.flex_root()
        vb.bind_custom_tag("setpoint", "[default]X/Set", bidirectional=True)
        out = view_to_disk(vb.build())
        self.assertTrue(out["propConfig"]["custom.setpoint"]["binding"]["config"]["bidirectional"])


if __name__ == "__main__":
    unittest.main()
