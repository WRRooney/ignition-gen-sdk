"""TagDataType — Ignition 8.3 dataType enum.

Uses the seed's tuple ``__new__`` pattern: members are ``(label, str_value, int_value)``
and ``_value_`` is set to ``str_value`` so that Pydantic's ``use_enum_values=True``
serializes to e.g. ``"Float8"`` (the string Ignition expects), not the tuple or
the integer or the human label.

Verified strings from samplequickstart_tags.json: Float8, Float4, Int4, Int8, etc.
"""
from enum import Enum


class TagDataType(Enum):
    # (label, str_value, int_value)
    BYTE = ("Byte", "Int1", 0)
    SHORT = ("Short", "Int2", 1)
    INTEGER = ("Integer", "Int4", 2)
    LONG = ("Long", "Int8", 3)
    FLOAT = ("Float", "Float4", 4)
    DOUBLE = ("Double", "Float8", 5)
    BOOLEAN = ("Boolean", "Boolean", 6)
    STRING = ("String", "String", 7)
    DATETIME = ("DateTime", "DateTime", 8)
    TEXT = ("Text (Deprecated: use TagDataType.STRING instead)", "Text", 10)
    BYTE_ARRAY = ("Byte Array", "Int1Array", 17)
    SHORT_ARRAY = ("Short Array", "Int2Array", 18)
    INTEGER_ARRAY = ("Integer Array", "Int4Array", 11)
    LONG_ARRAY = ("Long Array", "Int8Array", 12)
    FLOAT_ARRAY = ("Float Array", "Float4Array", 19)
    DOUBLE_ARRAY = ("Double Array", "Float8Array", 13)
    BOOLEAN_ARRAY = ("Boolean Array", "BooleanArray", 14)
    STRING_ARRAY = ("String Array", "StringArray", 15)
    DATETIME_ARRAY = ("DateTime Array", "DateTimeArray", 16)
    BINARY_DATA = ("Binary Data", "ByteArray", 20)
    DATASET = ("Dataset", "DataSet", 9)
    DOCUMENT = ("Document", "Document", 29)

    def __new__(cls, label, str_value, int_value):
        obj = object.__new__(cls)
        obj.label = label
        obj._value_ = str_value
        obj._int_value = int_value
        return obj
