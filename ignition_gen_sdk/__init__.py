"""ignition_gen_sdk: typed models, builders, gateway client and writers for Ignition 8.3.

This module is the stable import surface. Everything else under ``ignition_gen_sdk``
is importable but may move between minor versions.
"""

__version__ = "0.1.0"

from .backends.api_backend import ApiBackend
from .backends.api_client import IgnitionAPIClient, IgnitionAPIError
from .backends.disk_backend import DiskBackend
from .backends.project_disk import ProjectDiskBackend
from .backends.router import WriteRouter
from .backends.scan_client import ScanClient, ScanWarning
from .builders.tag_builder import TagBuilder
from .builders.view import ViewBuilder
from .config import Settings
from .models.tags.alarm import Alarm
from .models.tags.tag import Tag
from .models.tags.udt import UdtInstance, UdtType
from .models.views.component import Component
from .models.views.view import View
from .tools import seed_guard

__all__ = [
    "__version__",
    "Settings",
    "Tag",
    "UdtType",
    "UdtInstance",
    "Alarm",
    "View",
    "Component",
    "ViewBuilder",
    "TagBuilder",
    "IgnitionAPIClient",
    "IgnitionAPIError",
    "ApiBackend",
    "DiskBackend",
    "ProjectDiskBackend",
    "WriteRouter",
    "ScanClient",
    "ScanWarning",
    "seed_guard",
]
