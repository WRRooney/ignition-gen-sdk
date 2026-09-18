"""TagValueSource — Ignition 8.3 valueSource string values."""
from enum import Enum


class TagValueSource(Enum):
    DERIVED = "Derived"
    EXPRESSION = "expr"
    MEMORY = "memory"
    OPC = "opc"
    DB = "db"
    REFERENCE = "reference"
