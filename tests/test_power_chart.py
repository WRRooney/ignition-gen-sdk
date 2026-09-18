"""Tests for Power Chart authoring helpers.

ViewBuilder had no chart support; PowerChartProps didn't model pens. These lock
the new power_chart() factory + power_chart_pen()/tag_history_source() helpers.
"""
from __future__ import annotations

import unittest


class TestPowerChartHelpers(unittest.TestCase):
    def test_tag_history_source_shape(self):
        from ignition_gen_sdk.builders.view import tag_history_source
        s = tag_history_source("Historian", "default", "Tanks/T01/LevelHigh", gateway="Gateway")
        self.assertEqual(s, "histprov:Historian:/drv:Gateway:default:/tag:Tanks/T01/LevelHigh")

    def test_power_chart_pen_dict(self):
        from ignition_gen_sdk.builders.view import power_chart_pen
        pen = power_chart_pen("TankHigh", "histprov:Historian:/drv:G:default:/tag:X")
        self.assertEqual(pen["name"], "TankHigh")
        self.assertEqual(pen["data"]["source"], "histprov:Historian:/drv:G:default:/tag:X")
        self.assertEqual(pen["display"]["type"], "line")
        self.assertEqual(pen["plot"], 0)

    def test_power_chart_pen_color_emits_styles(self):
        from ignition_gen_sdk.builders.view import power_chart_pen
        pen = power_chart_pen("S", "src", color="#34C3FF")
        styles = pen["display"]["styles"]
        self.assertEqual(styles["normal"]["stroke"]["color"], "#34C3FF")
        self.assertEqual(styles["normal"]["fill"]["color"], "#34C3FF")
        self.assertEqual(styles["selected"]["stroke"]["opacity"], 1)
        # no color -> no styles block (gateway defaults)
        self.assertNotIn("styles", power_chart_pen("S", "src")["display"])

    def test_power_chart_factory_emits_pens(self):
        from ignition_gen_sdk.builders.view import ViewBuilder, power_chart_pen, tag_history_source
        from ignition_gen_sdk.serializers.view_disk import view_to_disk
        vb = ViewBuilder()
        vb.flex_root(direction="column")
        src = tag_history_source("Historian", "default", "Tanks/T01/LevelHigh", gateway="Gateway")
        vb.power_chart(name="UsageChart", pens=[power_chart_pen("TankHigh", src)])
        out = view_to_disk(vb.build())
        comp = out["root"]["children"][0]
        self.assertEqual(comp["type"], "ia.chart.powerchart")
        self.assertEqual(comp["meta"]["name"], "UsageChart")
        pen = comp["props"]["pens"][0]
        self.assertEqual(pen["name"], "TankHigh")
        self.assertTrue(pen["data"]["source"].startswith("histprov:Historian:/drv:Gateway:"))


if __name__ == "__main__":
    unittest.main()
