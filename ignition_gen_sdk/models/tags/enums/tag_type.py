"""TagType — Ignition 8.3 tag-type enum (verified from samplequickstart_tags.json)."""
from enum import Enum


class TagType(Enum):
    PROPERTY = "Property"
    NODE = "Node"
    FOLDER = "Folder"
    ATOMIC = "AtomicTag"
    UDT_INSTANCE = "UdtInstance"
    UDT = "UdtType"
    PROVIDER = "Provider"
