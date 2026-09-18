"""TagApiSerializer — flat JSON for POST /data/api/v1/tags/import.

Two functions:
- ``tag_to_api_dict``: emits one Tag as a flat dict (same shape Designer exports
  produce; matches Designer tag-export AtomicTag leaves).
- ``tags_to_import_body``: wraps a list of Tags in the Provider-root envelope
  observed in Designer tag exports:
  ``{"name": "", "tagType": "Provider", "tags": [...]}``.

The import API expects this Provider-root envelope rather than a bare
``{"tags": [...]}`` body (verified by a live smoke push).
"""
from __future__ import annotations

from typing import List, Union

from ..models.tags.tag import Tag
from ..models.tags.udt import UdtInstance


def tag_to_api_dict(tag: "Union[Tag, UdtInstance]") -> dict:
    """Flat dict for POST /data/api/v1/tags/import body.

    Accepts UdtInstance too: the import API takes instance nodes in the
    same envelope, and ``model_dump`` emits both identically.
    """
    return tag.model_dump(exclude_none=True, mode="json")


def tags_to_import_body(tags: "List[Union[Tag, UdtInstance]]") -> dict:
    """Provider-root envelope expected by /data/api/v1/tags/import.

    Shape matches a Designer tag export's root object. Empty ``name``
    means "this Provider" (path is supplied via the ``path`` query param).
    """
    return {
        "name": "",
        "tagType": "Provider",
        "tags": [tag_to_api_dict(t) for t in tags],
    }
