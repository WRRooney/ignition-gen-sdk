"""TagAlarmPriority — Ignition 8.3 alarm priority levels."""
from enum import Enum


class TagAlarmPriority(Enum):
    DIAGNOSTIC = "Diagnostic"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"
