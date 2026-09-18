"""Tests for `ign tag udt-type` CLI verb."""
from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


_UDT = {"name": "WaterTank", "tagType": "UdtType", "tags": [
    {"name": "Level", "tagType": "AtomicTag", "dataType": "Float8", "valueSource": "memory"}]}


class TestCliUdtType(unittest.TestCase):
    def test_help_lists_udt_type(self):
        from ignition_gen_sdk.cli import app
        r = _runner().invoke(app, ["tag", "--help"])
        self.assertEqual(r.exit_code, 0, msg=r.output)
        self.assertIn("udt-type", r.output)

    def test_dry_run_emits_udttype_payload(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "u.json"
            p.write_text(json.dumps(_UDT))
            r = _runner().invoke(app, ["tag", "udt-type", "--provider", "default",
                                       "--path", "Loop/T15", "--file", str(p), "--dry-run"])
        self.assertEqual(r.exit_code, 0, msg=r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out[0]["tagType"], "UdtType")
        self.assertEqual(out[0]["name"], "WaterTank")

    def test_bad_json_rejected(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"; p.write_text("{nope")
            r = _runner().invoke(app, ["tag", "udt-type", "--file", str(p)])
        self.assertEqual(r.exit_code, 1)
        self.assertIn("--file", r.stderr)


if __name__ == "__main__":
    unittest.main()
