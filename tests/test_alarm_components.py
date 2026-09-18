"""Tests for the built-in Perspective alarm components.

Locks the ViewBuilder.alarm_status_table() / alarm_journal_table() factories that
emit ia.display.alarmstatustable (live) and ia.display.alarmjournaltable (history).
Props models are permissive (extra="allow") so any passthrough prop survives.
"""
from __future__ import annotations

import unittest


class TestAlarmComponents(unittest.TestCase):
    def test_alarm_status_table_type_and_passthrough(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        from ignition_gen_sdk.serializers.view_disk import view_to_disk
        vb = ViewBuilder()
        vb.flex_root(direction="column")
        vb.alarm_status_table(name="ActiveAlarms", alarmFilter={"priority": "High"})
        out = view_to_disk(vb.build())
        comp = out["root"]["children"][0]
        self.assertEqual(comp["type"], "ia.display.alarmstatustable")
        self.assertEqual(comp["meta"]["name"], "ActiveAlarms")
        # Unenumerated prop rides through via extra="allow".
        self.assertEqual(comp["props"]["alarmFilter"], {"priority": "High"})

    def test_alarm_journal_table_type_and_passthrough(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        from ignition_gen_sdk.serializers.view_disk import view_to_disk
        vb = ViewBuilder()
        vb.flex_root(direction="column")
        vb.alarm_journal_table(name="AlarmHistory", columns=[{"field": "name"}])
        out = view_to_disk(vb.build())
        comp = out["root"]["children"][0]
        self.assertEqual(comp["type"], "ia.display.alarmjournaltable")
        self.assertEqual(comp["meta"]["name"], "AlarmHistory")
        self.assertEqual(comp["props"]["columns"], [{"field": "name"}])

    def test_both_tables_view_model_dumps(self):
        from ignition_gen_sdk.builders.view import ViewBuilder
        vb = ViewBuilder()
        vb.flex_root(direction="column")
        vb.alarm_status_table()
        vb.alarm_journal_table()
        view = vb.build()
        # model_dump must not raise; both components present.
        dumped = view.model_dump(by_alias=True, exclude_none=True, mode="json")
        types = [c["type"] for c in dumped["root"]["children"]]
        self.assertIn("ia.display.alarmstatustable", types)
        self.assertIn("ia.display.alarmjournaltable", types)


if __name__ == "__main__":
    unittest.main()
