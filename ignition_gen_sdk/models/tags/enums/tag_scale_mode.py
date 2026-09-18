"""TagScaleMode — Ignition 8.3 scaleMode enum.

Same tuple ``__new__`` pattern as TagDataType: ``_value_`` is the JSON string
so ``use_enum_values=True`` emits e.g. ``"Linear"``, not the tuple.
"""
from enum import Enum


class TagScaleMode(Enum):
    # (label, str_value, int_value)
    OFF = ("Off", "Off", 0)
    LINEAR = ("Linear", "Linear", 1)
    SQUARE_ROOT = ("Square Root", "SquareRoot", 2)
    EXPONENTIAL_FILTER = ("Exponential Filter", "ExponentialFilter", 3)
    BIT_INVERSION = ("Bit Inversion", "BitInversion", 4)

    def __new__(cls, label, str_value, int_value):
        obj = object.__new__(cls)
        obj.label = label
        obj._value_ = str_value
        obj._int_value = int_value
        return obj
