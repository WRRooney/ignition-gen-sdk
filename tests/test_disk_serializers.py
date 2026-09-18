"""disk serializers + UdtInstance model.

Behavior contracts:
- TagDiskSerializer wraps non-(name/tagType/tags) fields under "usr" ONLY when
  wrap_usr=True (MANAGED providers); the default emit is FLAT
  matching live MQTT Engine tags.json shape.
- UdtDiskSerializer is FLAT — NO "usr" wrapper anywhere — matching live
  a live UdtInstance udts.json shape.
- UdtInstance(name, typeId, parameters={...}) emits the canonical
  flat dict with tagType="UdtInstance".
- Top-level keys allowed in tag_to_disk_format output: name, tagType,
  tags, usr — nothing else.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


def _add_pkg_path() -> None:
    here = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(here))


_add_pkg_path()


class TestTagDiskSerializer(unittest.TestCase):
    def test_basic_usr_envelope(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tag_to_disk_format

        t = Tag(
            name="online",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
            readOnly=False,
            enabled=True,
        )
        d = tag_to_disk_format(t, wrap_usr=True)
        # Top-level keys: only name/tagType/tags/usr allowed
        for k in d:
            self.assertIn(
                k, {"name", "tagType", "tags", "usr"},
                f"unexpected top-level key: {k}",
            )
        self.assertEqual(d["name"], "online")
        self.assertEqual(d["tagType"], "AtomicTag")
        # dataType lives under usr, NOT at top level
        self.assertNotIn("dataType", d)
        self.assertIn("usr", d)
        self.assertEqual(d["usr"]["dataType"], "Boolean")
        self.assertEqual(d["usr"]["readOnly"], False)
        self.assertEqual(d["usr"]["enabled"], True)
        # No nested usr
        self.assertNotIn("usr", d["usr"])

    def test_no_usr_key_when_no_user_props(self) -> None:
        """A tag with only name/tagType (and no other emitted fields)
        should produce a dict with no 'usr' key. We can't directly
        construct a Tag without dataType etc. (the model requires
        them). So instead we check the rule: every top-level key
        must be in {name, tagType, tags, usr}.
        """
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tag_to_disk_format

        t = Tag(
            name="Folder1",
            tagType=TagType.FOLDER,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
        )
        d = tag_to_disk_format(t, wrap_usr=True)
        for k in d:
            self.assertIn(
                k, {"name", "tagType", "tags", "usr"},
                f"unexpected top-level key: {k}",
            )

    def test_recursive_children_wrapped(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tag_to_disk_format

        child = Tag(
            name="leaf",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
            enabled=True,
        )
        parent = Tag(
            name="parent",
            tagType=TagType.FOLDER,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
            tags=[child],
        )
        d = tag_to_disk_format(parent, wrap_usr=True)
        self.assertIn("tags", d)
        self.assertEqual(len(d["tags"]), 1)
        c = d["tags"][0]
        # Child must also be usr-wrapped, not flat
        for k in c:
            self.assertIn(
                k, {"name", "tagType", "tags", "usr"},
                f"unexpected child key: {k}",
            )
        self.assertEqual(c["name"], "leaf")
        self.assertEqual(c["tagType"], "AtomicTag")
        self.assertIn("usr", c)
        self.assertEqual(c["usr"]["dataType"], "Boolean")

    def test_tags_to_disk_returns_list(self) -> None:
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tags_to_disk

        t1 = Tag(
            name="a",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
        )
        t2 = Tag(
            name="b",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
        )
        out = tags_to_disk([t1, t2])
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "a")
        self.assertEqual(out[1]["name"], "b")


class TestUdtInstanceModel(unittest.TestCase):
    def test_emit_flat_no_usr(self) -> None:
        from ignition_gen_sdk.models.tags.udt import UdtInstance, UdtParameter

        u = UdtInstance(
            name="LightSW",
            typeId="ShellyLight",
            parameters={
                "deviceRoot": UdtParameter(
                    dataType="String", value="Utilities/Compressor/LightSW"
                )
            },
        )
        out = u.emit()
        self.assertEqual(out["name"], "LightSW")
        self.assertEqual(out["typeId"], "ShellyLight")
        self.assertEqual(out["tagType"], "UdtInstance")
        self.assertNotIn("usr", out)
        self.assertEqual(out["parameters"]["deviceRoot"]["dataType"], "String")
        self.assertEqual(
            out["parameters"]["deviceRoot"]["value"], "Utilities/Compressor/LightSW"
        )

    def test_credential_guard_inherits_to_udt(self) -> None:
        from ignition_gen_sdk.models.tags.udt import UdtInstance

        with self.assertRaises(ValueError):
            UdtInstance.model_validate(
                {"name": "X", "typeId": "T", "ciphertext": "x"}
            )


class TestUdtDiskSerializer(unittest.TestCase):
    def test_udts_to_disk_flat(self) -> None:
        from ignition_gen_sdk.models.tags.udt import UdtInstance, UdtParameter
        from ignition_gen_sdk.serializers.udt_disk import udts_to_disk

        u = UdtInstance(
            name="LightSW",
            typeId="ShellyLight",
            parameters={
                "deviceRoot": UdtParameter(
                    dataType="String", value="Utilities/Compressor/LightSW"
                ),
                "deviceId": UdtParameter(
                    dataType="String", value="shellypluswdus-048308dedf08"
                ),
            },
        )
        out = udts_to_disk([u])
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 1)
        d = out[0]
        # Flat format — NO usr wrapper anywhere
        self.assertNotIn("usr", d)
        self.assertEqual(d["name"], "LightSW")
        self.assertEqual(d["typeId"], "ShellyLight")
        self.assertEqual(d["tagType"], "UdtInstance")
        self.assertEqual(
            d["parameters"]["deviceRoot"]["value"], "Utilities/Compressor/LightSW"
        )

    def test_udts_to_disk_empty_list(self) -> None:
        from ignition_gen_sdk.serializers.udt_disk import udts_to_disk

        self.assertEqual(udts_to_disk([]), [])


if __name__ == "__main__":
    unittest.main()


class TestTagDiskFlatDefault(unittest.TestCase):
    """The DEFAULT emit is FLAT — 'usr' is the MANAGED-provider envelope.

    Regression guard: write_tags previously wrapped output unconditionally in
    'usr', which produced a shape no STANDARD provider uses. Every STANDARD
    provider's tags.json is flat; only MQTT Engine (MANAGED) is wrapped.
    """

    def _tag(self):
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_value_source import TagValueSource
        from ignition_gen_sdk.models.tags.tag import Tag

        return Tag(
            name="RebuildCache",
            tagType=TagType.ATOMIC,
            dataType=TagDataType.BOOLEAN,
            valueSource=TagValueSource.MEMORY,
            value=False,
        )

    def test_default_is_flat(self) -> None:
        from ignition_gen_sdk.serializers.tag_disk import tag_to_disk_format

        d = tag_to_disk_format(self._tag())
        self.assertNotIn("usr", d)
        self.assertEqual(d["dataType"], "Boolean")
        self.assertEqual(d["valueSource"], "memory")
        self.assertEqual(d["name"], "RebuildCache")

    def test_event_scripts_survive_both_envelopes(self) -> None:
        """A tag event script must reach disk in either shape."""
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tag_to_disk_format

        t = Tag.model_validate({
            "name": "RebuildCache", "tagType": "AtomicTag", "dataType": "Boolean",
            "valueSource": "memory", "value": False,
            "eventScripts": [{"eventid": "valueChanged", "script": "\tpass"}],
        })
        flat = tag_to_disk_format(t)
        self.assertEqual(flat["eventScripts"][0]["eventid"], "valueChanged")
        wrapped = tag_to_disk_format(t, wrap_usr=True)
        self.assertEqual(wrapped["usr"]["eventScripts"][0]["script"], "\tpass")

    def test_children_stay_flat(self) -> None:
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tags_to_disk

        parent = Tag.model_validate({
            "name": "Nav", "tagType": "Folder",
            "tags": [{"name": "RootPath", "tagType": "AtomicTag",
                      "dataType": "String", "valueSource": "memory"}],
        })
        out = tags_to_disk([parent])
        self.assertNotIn("usr", out[0])
        self.assertNotIn("usr", out[0]["tags"][0])
        self.assertEqual(out[0]["tags"][0]["dataType"], "String")

    def test_tags_json_comes_out_in_the_gateways_key_order(self) -> None:
        """Otherwise every value edit is a whole-file diff.

        Repointing ONE tag value used to rewrite all 87 lines of a tags.json
        because ign emitted Pydantic field order and the Designer emits
        ASCII-sorted keys with the children array last. The line that actually
        changed was unreviewable in the noise.
        """
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.serializers.tag_disk import tags_to_disk

        parent = Tag.model_validate({
            "name": "Nav", "tagType": "Folder",
            "tags": [{"name": "RootPath", "tagType": "AtomicTag",
                      "tooltip": "Nav root", "dataType": "String",
                      "valueSource": "memory", "value": "[default]System"}],
        })
        out = tags_to_disk([parent])
        self.assertEqual(list(out[0]), ["name", "tagType", "tags"])
        child = out[0]["tags"][0]
        self.assertEqual(list(child), sorted(child))
