"""TagAlarmMode — Ignition 8.3 alarm trigger modes.

Adds `WHEN_TRUE` and `WHEN_FALSE` per the 8.3 alarm-mode delta. These are
boolean-tag specific modes used when the alarm fires on the tag's literal
True/False value (no setpoint comparison).
"""
from enum import Enum


class TagAlarmMode(Enum):
    EQUAL = "Equality"
    NOT_EQUAL = "Inequality"
    ABOVE_SETPOINT = "AboveValue"
    BELOW_SETPOINT = "BelowValue"
    BETWEEN_SETPOINTS = "BetweenValues"
    OUTSIDE_SETPOINTS = "OutsideValues"
    OUT_OF_RANGE = "OutOfEngRange"
    BAD_QUALITY = "BadQuality"
    ANY_CHANGE = "AnyChange"
    BIT_STATE = "Bit"
    ON_CONDITION = "OnCondition"
    # 8.3 additions:
    WHEN_TRUE = "WhenTrue"    # Boolean tag: alarm when value is True
    WHEN_FALSE = "WhenFalse"  # Boolean tag: alarm when value is False
