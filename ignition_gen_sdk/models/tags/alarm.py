"""Alarm — Ignition 8.3 alarm definition (embedded in Tag.alarms).

Notes:
- Inherits IgnitionBaseModel (gains credential guard + ConfigDict).
- ``setpointA``, ``setpointB``, ``ackMode`` keep their non-None defaults
  (the gateway expects these on alarm objects); ``exclude_none=True`` will
  still emit them because the values are not None.
"""
from __future__ import annotations

from typing import Literal, Optional

from ..base import IgnitionBaseModel
from .enums.tag_alarm_mode import TagAlarmMode
from .enums.tag_alarm_priority import TagAlarmPriority


class Alarm(IgnitionBaseModel):
    # Main Properties
    name: str
    enabled: Optional[bool] = True
    priority: TagAlarmPriority = TagAlarmPriority.LOW
    timestampSource: Optional[Literal["System", "Value"]] = "System"
    label: Optional[str] = None
    displayPath: Optional[str] = None
    ackMode: Optional[Literal["Unused", "Auto", "Manual"]] = "Manual"
    notes: Optional[str] = None
    ackNotesReqd: Optional[bool] = False
    shelvingAllowed: Optional[bool] = True

    # Alarm Mode Properties
    mode: TagAlarmMode = TagAlarmMode.EQUAL
    setpointA: Optional[float] = 0.0
    inclusiveA: Optional[bool] = True
    setpointB: Optional[float] = 0.0
    inclusiveB: Optional[bool] = True
    anyChange: Optional[bool] = False
    bitOnZero: Optional[bool] = None
    bitPosition: Optional[int] = None
    activeCondition: Optional[bool] = None

    # Deadbands and Delays
    deadband: Optional[float] = None
    deadbandMode: Optional[Literal["Absolute", "Percent", "Off"]] = None
    timeOnDelaySeconds: Optional[int] = None
    timeOffDelaySeconds: Optional[int] = None

    # Notification Properties
    activePipeline: Optional[str] = ""
    clearPipeline: Optional[str] = ""
    ackPipeline: Optional[str] = ""
