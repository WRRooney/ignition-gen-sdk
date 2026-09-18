"""DiskBackend.write_udt_types — UDT *definition* disk write.

Writes udts.json + unary-resource.json under
config/resources/core/ignition/tag-type-definition/<provider>/<path>/.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _settings_with_root(root: Path):
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-disk-tests"}, clear=False):
        from ignition_gen_sdk.config import Settings
        return Settings(ignition_data_root=root)


def _watertank():
    from ignition_gen_sdk.models.tags.udt import UdtType
    from ignition_gen_sdk.models.tags.tag import Tag
    return UdtType(name="WaterTank", tags=[
        Tag(name="Level", tagType="AtomicTag", dataType="Float8", valueSource="memory"),
        Tag(name="Running", tagType="AtomicTag", dataType="Boolean", valueSource="memory"),
    ])


class TestWriteUdtTypes(unittest.TestCase):
    def test_writes_under_tag_type_definition(self):
        from ignition_gen_sdk.backends.disk_backend import DiskBackend
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            be = DiskBackend(_settings_with_root(root))
            dest = be.write_udt_types("default", "Loop/T14", [_watertank()])
            # correct resource-type directory
            self.assertIn("ignition/tag-type-definition/default/Loop/T14", str(dest))
            udts = json.loads((dest / "udts.json").read_text())
            self.assertEqual(udts[0]["tagType"], "UdtType")
            self.assertEqual(udts[0]["name"], "WaterTank")
            sidecar = json.loads((dest / "unary-resource.json").read_text())
            self.assertEqual(sidecar["files"], ["udts.json"])

    def test_path_containment_guard(self):
        from ignition_gen_sdk.backends.disk_backend import DiskBackend
        with tempfile.TemporaryDirectory() as d:
            be = DiskBackend(_settings_with_root(Path(d)))
            with self.assertRaises(ValueError):
                be.write_udt_types("default", "../../escape", [_watertank()])


if __name__ == "__main__":
    unittest.main()
