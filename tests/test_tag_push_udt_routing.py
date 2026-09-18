"""UdtInstance push routing + sidecar union.

A fully-specified UdtInstance used to pass Tag validation and get MIS-FILED
into tags.json by ``tag push --backend disk``, with the rewritten sidecar
listing ONLY tags.json — un-manifesting the folder's udts.json (its UDT
instances would vanish on a cold gateway load). Locked-in fixes:

1. ``_load_tags_file`` validates ``tagType == "UdtInstance"`` items as
   :class:`UdtInstance`.
2. ``tag push`` REJECTS instances unless ``--backend api`` and redirects to
   ``tag udt-instance`` (the udts.json writer).
3. ``DiskBackend._write_payload_with_sidecar`` manifests the UNION of data
   files present (tags.json + udts.json can coexist in one folder resource).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

INSTANCE = {
    "name": "Data Source 1",
    "tagType": "UdtInstance",
    "typeId": "Reports/DataSourceConfig/AlarmHistory",
    "tags": [
        {"name": "name", "dataType": "String", "tagType": "AtomicTag",
         "value": "Alarm Events", "valueSource": "memory"},
    ],
}


def _settings_with_root(root: Path):
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-disk-tests"}, clear=False):
        from ignition_gen_sdk.config import Settings
        return Settings(ignition_data_root=root)


class TestLoaderRoutesInstances(unittest.TestCase):
    def test_instance_dict_validates_as_udt_instance(self):
        from ignition_gen_sdk.cli.cmd_tag import _load_tags_file
        from ignition_gen_sdk.models.tags.udt import UdtInstance
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inst.json"
            p.write_text(json.dumps([INSTANCE]))
            loaded = _load_tags_file(p)
        self.assertEqual(len(loaded), 1)
        self.assertIsInstance(loaded[0], UdtInstance)


class TestPushRejectsInstancesOffApi(unittest.TestCase):
    def test_disk_backend_push_redirects_to_udt_instance(self):
        from typer.testing import CliRunner
        from ignition_gen_sdk.cli import app
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inst.json"
            p.write_text(json.dumps(INSTANCE))
            result = CliRunner().invoke(
                app, ["tag", "push", "--backend", "disk", "--provider", "default",
                      "--path", "X/Queries", "--file", str(p)])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("udt-instance", result.output)


class TestSidecarUnion(unittest.TestCase):
    def test_udts_write_keeps_tags_json_manifested(self):
        from ignition_gen_sdk.backends.disk_backend import DiskBackend
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.models.tags.udt import UdtInstance
        with tempfile.TemporaryDirectory() as d:
            be = DiskBackend(_settings_with_root(Path(d)))
            dest = be.write_tags("default", "X/Queries", [
                Tag(name="plain", tagType="AtomicTag", dataType="Int4",
                    valueSource="memory", value=1)])
            self.assertEqual(
                json.loads((dest / "unary-resource.json").read_text())["files"],
                ["tags.json"])
            be.write_udts("default", "X/Queries",
                          [UdtInstance.model_validate(INSTANCE)])
            self.assertEqual(
                json.loads((dest / "unary-resource.json").read_text())["files"],
                ["tags.json", "udts.json"])


if __name__ == "__main__":
    unittest.main()
