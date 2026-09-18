"""Tests for UdtType (UDT *definition*) model + serializer.

Previously ign could not author a UDT definition. UdtType
+ udt_types_to_disk emit the tag-type-definition udts.json shape.
"""
from __future__ import annotations

import unittest


class TestUdtType(unittest.TestCase):
    def _watertank(self):
        from ignition_gen_sdk.models.tags.udt import UdtType
        from ignition_gen_sdk.models.tags.tag import Tag
        return UdtType(
            name="WaterTank",
            tags=[
                Tag(name="Level", tagType="AtomicTag", dataType="Float8", valueSource="memory"),
                Tag(name="Setpoint", tagType="AtomicTag", dataType="Float8", valueSource="memory"),
                Tag(name="Running", tagType="AtomicTag", dataType="Boolean", valueSource="memory"),
            ],
        )

    def test_emits_udttype_definition_shape(self):
        from ignition_gen_sdk.serializers.udt_disk import udt_types_to_disk
        out = udt_types_to_disk([self._watertank()])
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual(d["name"], "WaterTank")
        self.assertEqual(d["tagType"], "UdtType")
        names = [t["name"] for t in d["tags"]]
        self.assertEqual(names, ["Level", "Setpoint", "Running"])
        self.assertEqual(d["tags"][0]["dataType"], "Float8")
        self.assertEqual(d["tags"][2]["dataType"], "Boolean")
        # no 'usr' wrapper, no typeColor/parameters when unset (exclude_none)
        self.assertNotIn("usr", d)
        self.assertNotIn("typeColor", d)

    def test_parameters_and_typecolor(self):
        from ignition_gen_sdk.models.tags.udt import UdtType, UdtTypeParameter
        from ignition_gen_sdk.serializers.udt_disk import udt_types_to_disk
        t = UdtType(name="HOA", typeColor=-2763307,
                    parameters={"mode": UdtTypeParameter(dataType="Integer", value=1)})
        d = udt_types_to_disk([t])[0]
        self.assertEqual(d["typeColor"], -2763307)
        self.assertEqual(d["parameters"]["mode"]["dataType"], "Integer")
        self.assertEqual(d["parameters"]["mode"]["value"], 1)


class TestTagTypeConditionalValidation(unittest.TestCase):
    """DataType/valueSource are Optional on the model so Folder member tags
    (no dataType/valueSource in Ignition's on-disk format) validate — but the
    requirement is enforced CONDITIONALLY by tagType, so AtomicTag still requires
    both and a UdtType node is rejected as a standalone Tag (still rejected)."""

    def test_folder_member_tag_needs_no_datatype_or_valuesource(self):
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        # Must NOT raise — this is the base-UDT Setpoints/ sub-folder case.
        f = Tag(name="Setpoints", tagType=TagType.FOLDER)
        self.assertIsNone(f.dataType)
        self.assertIsNone(f.valueSource)

    def test_atomic_tag_still_requires_datatype_and_valuesource(self):
        import pydantic
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        from ignition_gen_sdk.models.tags.enums.tag_datatype import TagDataType
        with self.assertRaises(pydantic.ValidationError):
            Tag(name="X", tagType=TagType.ATOMIC, dataType=TagDataType.DOUBLE)  # no valueSource
        with self.assertRaises(pydantic.ValidationError):
            Tag(name="X", tagType=TagType.ATOMIC)  # neither

    def test_udttype_rejected_as_standalone_tag(self):
        import pydantic
        from ignition_gen_sdk.models.tags.tag import Tag
        from ignition_gen_sdk.models.tags.enums.tag_type import TagType
        with self.assertRaises(pydantic.ValidationError):
            Tag(name="WaterTank", tagType=TagType.UDT)


if __name__ == "__main__":
    unittest.main()
