"""Validation helpers for Ignition-correctness of authored artifacts.

Currently: whitelists of built-in Ignition **expression functions** and
**system.* scripting functions**, plus checkers that flag references to
names that do not exist (a runtime parse/AttributeError that otherwise passes
JSON/model validation — the "validates != runtime-correct" bug class).
"""

from .ignition_builtins import (
    EXPRESSION_FUNCTIONS,
    SYSTEM_SUBPACKAGES,
    SYSTEM_FUNCTIONS,
    LEAF_ENFORCED_SUBPACKAGES,
    unknown_expression_functions,
    unknown_system_calls,
)
from .material_icons import MATERIAL_ICONS, unknown_material_icon

__all__ = [
    "EXPRESSION_FUNCTIONS",
    "SYSTEM_SUBPACKAGES",
    "SYSTEM_FUNCTIONS",
    "LEAF_ENFORCED_SUBPACKAGES",
    "unknown_expression_functions",
    "unknown_system_calls",
    "MATERIAL_ICONS",
    "unknown_material_icon",
]
