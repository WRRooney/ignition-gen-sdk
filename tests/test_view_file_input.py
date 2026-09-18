"""Tests for `ign view build/write --file`.

Before this, build/write only emitted a hardcoded demo view. `--file` loads a
disk-shape view.json, validates it through the View model, and emits/writes it.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


def _custom_view_json() -> str:
    """A non-demo view authored via the library, in disk shape."""
    from ignition_gen_sdk.builders.view import ViewBuilder
    from ignition_gen_sdk.serializers.view_disk import view_to_disk
    vb = ViewBuilder()
    vb.flex_root(direction="column")
    vb.label(text="Tank Status", name="TankStatusLabel")
    vb.label(text="", name="TankLevelLabel").bind_text("[default]Loop/T01/WaterTankLevel")
    return json.dumps(view_to_disk(vb.build()))


class TestViewBuildFile(unittest.TestCase):
    def test_build_file_emits_supplied_view_not_demo(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "view.json"
            p.write_text(_custom_view_json())
            result = _runner().invoke(app, ["view", "build", "--file", str(p)])
        self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
        data = json.loads(result.stdout)
        names = [c["meta"]["name"] for c in data["root"]["children"]]
        self.assertEqual(names, ["TankStatusLabel", "TankLevelLabel"])
        # the bound label carries the tag binding through the round-trip
        bound = data["root"]["children"][1]
        self.assertEqual(
            bound["propConfig"]["props.text"]["binding"]["config"]["tagPath"],
            "[default]Loop/T01/WaterTankLevel",
        )

    def test_build_file_rejects_bad_json(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{not json")
            result = _runner().invoke(app, ["view", "build", "--file", str(p)])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("--file", result.stderr)


class TestViewWriteFile(unittest.TestCase):
    def test_write_file_dry_run_uses_supplied_view(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "view.json"
            p.write_text(_custom_view_json())
            result = _runner().invoke(
                app,
                ["view", "write", "--project", "Demo",
                 "--view-path", "Loop/T03/TankStatus", "--file", str(p), "--dry-run"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
        self.assertIn("TankStatusLabel", result.stdout)
        self.assertIn("Loop/T03/TankStatus", result.stdout)


if __name__ == "__main__":
    unittest.main()
