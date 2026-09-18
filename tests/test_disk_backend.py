"""DiskBackend atomic write + layer guard.

Behavior contracts:
- write_tags("default", "Smoke/DiskTest", [tag]) creates
  config/resources/core/ignition/tag-definition/default/Smoke/DiskTest/
  tags.json AND unary-resource.json.
- tags.json is a JSON list of tag objects; 'usr'-wrapped only with wrap_usr=True.
- unary-resource.json exact shape: scope=G, version=1, restricted=false,
  overridable=true, files=["tags.json"], attributes={"config":{}}.
  No "signature", no "lastModification".
- write_udts produces udts.json with files=["udts.json"] in sidecar.
- Atomic write uses .tmp file then Path.replace() — no .tmp left over.
- Path segment "light:0" is encoded as %3a / %3A by urllib.parse.quote.
- Writes that resolve under config/resources/local/ raise ValueError.

Tests use a temp Settings.ignition_data_root so we never mutate the real
gateway tree.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _add_pkg_path() -> None:
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


def _settings_with_root(root: Path):
    """Build a Settings whose ignition_data_root is a temp directory."""
    with patch.dict(os.environ, {"IGNITION_API_TOKEN": "test:dummy-for-disk-tests"}, clear=False):
        from ignition_gen_sdk.config import Settings

        return Settings(ignition_data_root=root)


def _make_tag():
    from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
    from ignition_gen_sdk.models.tags.enums.tag_type import TagType
    from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
    from ignition_gen_sdk.models.tags.tag import Tag

    return Tag(
        name="TestLevel",
        tagType=TagType.ATOMIC,
        dataType=TagDataType.DOUBLE,
        valueSource=TagValueSource.MEMORY,
        enabled=True,
    )


def _make_udt():
    from ignition_gen_sdk.models.tags.udt import UdtInstance, UdtParameter

    return UdtInstance(
        name="LightSW",
        typeId="ShellyLight",
        parameters={
            "deviceRoot": UdtParameter(
                dataType="String", value="Utilities/Compressor/LightSW"
            )
        },
    )


class TestEncodeSegment(unittest.TestCase):
    def test_colon_encoded(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import _encode_segment

        # Only ':' is substituted, and only with
        # lowercase %3a to match the gateway's observed encoding
        # (live MQTT Engine paths emit 'light%3a0').
        out = _encode_segment("light:0")
        self.assertEqual(out, "light%3a0")

    def test_traversal_blocked(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import _encode_segment

        # Inner '/' is rejected outright (raises ValueError) — a
        # single segment cannot contain a path separator. This blocks
        # traversal AND multi-segment-in-single-segment misuse.
        with self.assertRaises(ValueError):
            _encode_segment("../local")

    def test_literal_space_preserved(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import _encode_segment

        # The gateway uses LITERAL spaces in disk paths (verified
        # across samplequickstart 'Home Large' / 'Layout Card' and live
        # 'MQTT Engine' fixtures). The encoder must not transform them.
        self.assertEqual(_encode_segment("MQTT Engine"), "MQTT Engine")
        self.assertEqual(_encode_segment("Home Large"), "Home Large")


class TestDiskBackendWriteTags(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_tags_and_unary_resource(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        tag = _make_tag()
        dest = backend.write_tags("default", "Smoke/DiskTest", [tag], wrap_usr=True)

        self.assertTrue(dest.is_dir())
        tags_file = dest / "tags.json"
        res_file = dest / "unary-resource.json"
        self.assertTrue(tags_file.exists(), "tags.json missing")
        self.assertTrue(res_file.exists(), "unary-resource.json missing")

        # tags.json — usr-wrapped JSON list
        tags_data = json.loads(tags_file.read_text())
        self.assertIsInstance(tags_data, list)
        self.assertEqual(tags_data[0]["name"], "TestLevel")
        self.assertIn("usr", tags_data[0])
        self.assertNotIn("dataType", tags_data[0])
        self.assertEqual(tags_data[0]["usr"]["dataType"], "Float8")

        # unary-resource.json — exact shape
        res = json.loads(res_file.read_text())
        self.assertEqual(res["scope"], "G")
        self.assertEqual(res["version"], 1)
        self.assertEqual(res["restricted"], False)
        self.assertEqual(res["overridable"], True)
        self.assertEqual(res["files"], ["tags.json"])
        self.assertEqual(res["attributes"], {"config": {}})
        self.assertNotIn("signature", res)
        self.assertNotIn("lastModification", res)
        # Key ORDER matters as much as the shape: the gateway writes 'files'
        # before 'attributes', and a sidecar rewritten the other way round is
        # eight lines of diff on every tag write.
        self.assertEqual(
            list(res),
            ["scope", "version", "restricted", "overridable", "files",
             "attributes"],
        )

    def test_tag_payloads_are_html_safe_escaped_like_a_designer_save(self) -> None:
        """Gson escapes = and ' inside strings; plain json.dumps does not.

        A tag event script is full of both, so without this every write churns
        the whole script line even when the script did not change.
        """
        from ignition_gen_sdk.backends.disk_backend import DiskBackend
        from ignition_gen_sdk.models.tags.tag import Tag

        backend = DiskBackend(_settings_with_root(self._root))
        tag = Tag.model_validate({
            "name": "RebuildCache", "tagType": "AtomicTag",
            "dataType": "Boolean", "valueSource": "memory", "value": False,
            "tooltip": "the cache's trigger",
            "eventScripts": [{"eventid": "valueChanged", "script": "\tx = 1"}],
        })
        dest = backend.write_tags("default", "Smoke/Escapes", [tag])
        raw = (dest / "tags.json").read_text()
        self.assertIn("\\u003d", raw)
        self.assertIn("\\u0027", raw)
        self.assertEqual(json.loads(raw)[0]["tooltip"], "the cache's trigger")

    def test_no_tmp_file_left_after_write(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        dest = backend.write_tags("default", "Smoke/Atomic", [_make_tag()])

        # Atomic write writes to .tmp then renames; no .tmp file remains.
        leftover = list(dest.glob("*.tmp"))
        self.assertEqual(leftover, [], f"leftover tmp files: {leftover}")

    def test_path_under_core_only(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        dest = backend.write_tags("default", "P1", [_make_tag()])
        # Resolved path must contain /config/resources/core/
        self.assertIn(
            "/config/resources/core/",
            str(dest.resolve()),
            f"unexpected path: {dest}",
        )

    def test_colon_in_path_encoded_on_disk(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        dest = backend.write_tags(
            "default", "Smoke/light:0", [_make_tag()]
        )
        s = str(dest)
        # Either case acceptable; raw colon must NOT be in the path.
        self.assertTrue(
            "light%3a0" in s or "light%3A0" in s,
            f"colon not encoded in path: {s}",
        )
        # The literal colon must be gone for that segment.
        # (Drive letters on Windows would have a colon; we're on Linux.)
        self.assertNotIn(":", dest.name)


class TestDiskBackendWriteUdts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_udts_and_sidecar(self) -> None:
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        dest = backend.write_udts("Plant", "Utilities/Compressor", [_make_udt()])

        udts_file = dest / "udts.json"
        res_file = dest / "unary-resource.json"
        self.assertTrue(udts_file.exists())
        self.assertTrue(res_file.exists())

        udts_data = json.loads(udts_file.read_text())
        self.assertEqual(udts_data[0]["name"], "LightSW")
        self.assertEqual(udts_data[0]["typeId"], "ShellyLight")
        self.assertEqual(udts_data[0]["tagType"], "UdtInstance")
        self.assertNotIn("usr", udts_data[0])

        res = json.loads(res_file.read_text())
        self.assertEqual(res["files"], ["udts.json"])
        self.assertEqual(res["scope"], "G")
        self.assertEqual(res["attributes"], {"config": {}})


class TestDiskBackendLayerGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rejects_local_path(self) -> None:
        """If a DiskBackend is constructed pointing at config/resources/local
        (which we model by passing a fake root and overriding _core_root),
        write_tags must raise ValueError.
        """
        from ignition_gen_sdk.backends.disk_backend import DiskBackend

        backend = DiskBackend(_settings_with_root(self._root))
        # Point _core_root at a path under .../local/ to simulate misuse.
        local_path = self._root / "config" / "resources" / "local"
        local_path.mkdir(parents=True, exist_ok=True)
        backend._core_root = local_path

        with self.assertRaises(ValueError) as cm:
            backend.write_tags("default", "Test", [_make_tag()])
        self.assertIn("local", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
