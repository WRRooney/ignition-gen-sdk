"""Tests for `ign tag build/push --file`.

Mirrors the view --file capability: load tag(s) from JSON, validate via the Tag
model, emit/push instead of the hardcoded demo tag.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _runner():
    from typer.testing import CliRunner
    return CliRunner()


_MEMORY_TAG = {
    "name": "WaterTankLevel",
    "tagType": "AtomicTag",
    "dataType": "Float8",
    "valueSource": "memory",
    "value": 42.0,
    "engUnit": "%",
}


class TestTagBuildFile(unittest.TestCase):
    def test_build_file_emits_supplied_tag_as_import_body(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tag.json"
            p.write_text(json.dumps(_MEMORY_TAG))
            result = _runner().invoke(app, ["tag", "build", "--file", str(p)])
        self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body["tagType"], "Provider")
        self.assertEqual(len(body["tags"]), 1)
        self.assertEqual(body["tags"][0]["name"], "WaterTankLevel")
        # NOT the demo tag
        self.assertNotIn("SmokeTestLevel", result.stdout)

    def test_build_file_accepts_list_and_import_body(self):
        from ignition_gen_sdk.cli import app
        for payload in ([_MEMORY_TAG], {"name": "", "tagType": "Provider", "tags": [_MEMORY_TAG]}):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "tags.json"
                p.write_text(json.dumps(payload))
                result = _runner().invoke(app, ["tag", "build", "--file", str(p)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["tags"][0]["name"], "WaterTankLevel")

    def test_build_file_does_not_silently_unwrap_udttype(self):
        """A UdtType node has a 'tags' key but is NOT a Provider
        import body. It must fail with a clear error, not be silently unwrapped
        into loose member tags (which drops the UdtType wrapper)."""
        from ignition_gen_sdk.cli import app
        udt = {
            "name": "WaterTank", "tagType": "UdtType",
            "tags": [{"name": "Level", "tagType": "AtomicTag",
                      "dataType": "Float8", "valueSource": "memory"}],
        }
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "udt.json"
            p.write_text(json.dumps(udt))
            result = _runner().invoke(app, ["tag", "build", "--file", str(p)])
        self.assertEqual(result.exit_code, 1, msg=result.stdout)
        # the wrapper must NOT have been silently stripped into a Provider body
        self.assertNotIn('"tagType": "Provider"', result.stdout)

    def test_build_file_rejects_bad_json(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{nope")
            result = _runner().invoke(app, ["tag", "build", "--file", str(p)])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("--file", result.stderr)


class TestTagPushFile(unittest.TestCase):
    def test_push_file_dry_run_uses_supplied_tag(self):
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tag.json"
            p.write_text(json.dumps(_MEMORY_TAG))
            result = _runner().invoke(
                app,
                ["tag", "push", "--provider", "default", "--path", "Loop/T04",
                 "--file", str(p), "--dry-run"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.stdout + result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body["tags"][0]["name"], "WaterTankLevel")
        self.assertNotIn("SmokeTestLevel", result.stdout)


if __name__ == "__main__":
    unittest.main()
