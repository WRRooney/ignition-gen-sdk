"""Binding-related enums: TagBindingMode, HttpMethod, TimeUnits, TagHistoryAggregation."""
from enum import Enum


class TagBindingMode(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    EXPRESSION = "expression"


class HttpMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    TRACE = "TRACE"
    CONNECT = "CONNECT"


class TimeUnits(Enum):
    MS = "MS"
    SEC = "SEC"
    MIN = "MIN"
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class TagHistoryAggregation(Enum):
    """Aggregation modes for tag-history bindings.

    Fixture-verified: MIN_MAX ("MinMax") observed in
    Components/Component Views/Charts/Time Series Chart/view.json and
    Ignition 101/Feature Views/Application/Historical Data/view.json.

    The other 12 values are extrapolated from Ignition 8.3 documentation
    and may need gateway-side correction if any string is wrong. The
    builder accepts any enum member; the gateway will reject unknown
    aggregates at view load (surfaces via the PayloadError
    taxonomy on IgnitionAPIClient).
    """
    AVG = "Average"
    MIN = "Min"
    MAX = "Max"
    SUM = "Sum"
    LAST_VALUE = "LastValue"
    SIMPLE_AVG = "SimpleAverage"
    VARIANCE = "Variance"
    STD_DEV = "StdDev"
    MIN_MAX = "MinMax"          # VERIFIED from Designer-exported fixtures
    RANGE = "Range"
    COUNT = "Count"
    DURATION_ON = "DurationOn"
    DURATION_OFF = "DurationOff"
