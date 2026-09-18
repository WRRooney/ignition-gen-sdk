"""TagHistoryBinding — Ignition 8.3 tag-history binding (most complex single binding).

Discriminator: `type: Literal["tag-history"]` — WITH HYPHEN. Distinct from
the "expression" / "expr" / "expr-struct" / "query" / "tag" / "property"
values used by the other binding types.

Gateway field names differ from the ergonomic builder kwargs:

    Spec said      Gateway emits       Model field name     Builder kwarg name
    ----------     ----------------    ------------------   ------------------
    paths          tags                tags                 paths
    queryMode      (not observed)      queryMode (Opt)      query_mode
    aggregationMode aggregate          aggregate            aggregation_mode
    range          dateRange           dateRange            range
    returnSize     returnSize          returnSize           return_size or kwarg-pair
    valueMode      (not observed)      valueMode (Opt)      value_mode

`aggregate` is a TOP-LEVEL config field, NOT per-tag.

Verified live shapes:

FIXTURE 1 — relative range, single tag, with polling. From
Ignition 101/Feature Views/Perspective Features/Bindings/view.json line 870-907:

    {"config": {
       "avoidScanClassValidation": true,
       "dateRange": {"mostRecent": "1", "mostRecentUnits": "MIN"},
       "ignoreBadQuality": false,
       "polling": {"enabled": true, "rate": "1"},
       "preventInterpolation": false,
       "returnFormat": "Wide",
       "returnSize": {"type": "RAW"},
       "tags": [{"path": "[Sample_Tags]Realistic/Realistic0"}],
       "valueFormat": "DATASET"
     },
     "type": "tag-history"}

FIXTURE 2 — absolute range, tags as expression-string, aggregate=MinMax. From
Ignition 101/Feature Views/Application/Historical Data/view.json line 605-628:

    {"config": {
       "aggregate": "MinMax",
       "avoidScanClassValidation": true,
       "dateRange": {"endDate": "{...}", "startDate": "{...}"},
       "enableValueCache": true,
       "ignoreBadQuality": false,
       "preventInterpolation": false,
       "returnFormat": "Wide",
       "returnSize": {"numRows": "100", "type": "FIXED"},
       "tags": "{parent.custom.selectedTags}",
       "valueFormat": "DATASET"
     },
     "type": "tag-history"}

DateRange is a Pydantic v2 callable-discriminator union.
Neither variant has a `type` field — the discriminator
inspects dict keys to choose DurationRange (has `mostRecent`) vs AbsoluteRange
(has `startDate`/`endDate`).

The `tags` field is unusual: it accepts list[TagHistoryTag] for the canonical
case OR a property-binding-expression string (like `"{view.custom.tagPaths}"`)
that the gateway accepts as-is. The @field_validator
preserves the string when it looks like an expression (starts with `{` ends
with `}`) and wraps single-path strings / list-of-strings into list[TagHistoryTag].

Polling sub-object is the shared `PollingConfig` from `bindings/query.py` —
same shape, same string-typed rate, same int->str coercion validator.

`enableValueCache: Optional[bool]` is modeled because the
Application/Historical Data/view.json fixture emits it; IgnitionBaseModel's
extra='forbid' would otherwise reject construction from that fixture.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Discriminator, Field, model_serializer
from pydantic import Tag as PydTag
from pydantic import field_validator

from ..models.base import IgnitionBaseModel
from ..transforms import Transform  # noqa: F401 — required so TagHistoryBinding.model_rebuild() resolves list["Transform"]
from ._emit import strip_binding_defaults
from .enums import TagHistoryAggregation
from .query import PollingConfig


# ----- TagHistoryTag -----


class TagHistoryTag(IgnitionBaseModel):
    """A single tag entry inside TagHistoryBindingConfig.tags.

    Gateway emits as `{"path": "[provider]Path"}` — only one field, no metadata.
    """
    path: str


# ----- DateRange variants -----


class DurationRange(IgnitionBaseModel):
    """Relative ("rolling") date range — last N <units> from now.

    Gateway stores `mostRecent` as a STRING even when the value is numeric;
    this lock matches every observed fixture.
    """
    mostRecent: str
    mostRecentUnits: Literal[
        "MS", "SEC", "MIN", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"
    ]


class AbsoluteRange(IgnitionBaseModel):
    """Absolute date range — specific start/end timestamps.

    Both fields accept either:
    - str: expression-language string like `"{view.custom.startDate}"`
      (the typical gateway shape — fixtures bind these to view custom params),
    - datetime: a Python datetime instance (model_dump(mode='json') serializes
      to ISO 8601).
    """
    startDate: str | datetime
    endDate: str | datetime


def _range_discriminator(v):
    """Callable discriminator for the DateRange union (Pydantic v2 idiom).

    Neither DurationRange nor AbsoluteRange has a `type` discriminator field,
    so we inspect the dict keys (for raw dict inputs) or attribute presence
    (for already-instantiated models passed via validate_python).

    """
    if isinstance(v, dict):
        if "mostRecent" in v:
            return "duration"
        if "startDate" in v or "endDate" in v:
            return "absolute"
        return None
    if hasattr(v, "mostRecent"):
        return "duration"
    if hasattr(v, "startDate") or hasattr(v, "endDate"):
        return "absolute"
    return None


DateRange = Annotated[
    Union[
        Annotated[DurationRange, PydTag("duration")],
        Annotated[AbsoluteRange, PydTag("absolute")],
    ],
    Discriminator(_range_discriminator),
]


# ----- ReturnSize -----


class ReturnSize(IgnitionBaseModel):
    """How the gateway sizes the result set.

    type=="RAW": all points within the range; numRows omitted.
    type=="FIXED": numRows interpolated rows.

    `numRows` is a STRING on the wire (matching the polling.rate idiom
    of bind_query) — the gateway emits "100", "300" as strings even though
    semantically they are integers. Modeled as Optional[str] so the
    type=="RAW" case can omit it cleanly.
    """
    type: Literal["RAW", "FIXED"]
    numRows: Optional[str] = None


# ----- TagHistoryBindingConfig -----


class TagHistoryBindingConfig(IgnitionBaseModel):
    """Config sub-object for TagHistoryBinding.

    REQUIRED:
    - tags: either list[TagHistoryTag] OR an expression-string (passthrough).

    Field-name corrections vs stale spec (see module docstring): the model
    uses the gateway-emitted names (tags / dateRange / aggregate /
    returnSize / valueFormat), NOT the ergonomic builder kwarg names.

    The full surface includes several Optional fields that are documented
    in Ignition 8.3 docs but were NOT observed in Designer-exported
    fixtures (queryMode, valueMode, bounds, includeBoundingValues, deadband).
    Modeling them as Optional[X]=None keeps the surface complete; exclude_none
    drops them from emit. Gateway-side rejection
    of bad values surfaces via the PayloadError taxonomy.
    """

    # REQUIRED — union type allows expression-string passthrough.
    tags: list[TagHistoryTag] | str

    # OPTIONAL fields observed in fixtures
    dateRange: Optional[DateRange] = None
    aggregate: Optional[TagHistoryAggregation] = None
    returnSize: Optional[ReturnSize] = None
    returnFormat: Optional[Literal["Wide", "Tall", "Calculations"]] = None
    valueFormat: Optional[str] = None
    polling: Optional[PollingConfig] = None
    ignoreBadQuality: Optional[bool] = None
    preventInterpolation: Optional[bool] = None
    avoidScanClassValidation: Optional[bool] = None
    # Observed in Application/Historical Data/view.json fixture
    enableValueCache: Optional[bool] = None

    # OPTIONAL fields documented in 8.3 docs but not observed in fixtures
    queryMode: Optional[Literal["Realtime", "Historical"]] = None
    valueMode: Optional[Literal["delta", "cumulative"]] = None
    bounds: Optional[str] = None
    includeBoundingValues: Optional[bool] = None
    deadband: Optional[float] = None

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> Any:
        """Normalize the tags input to one of two final shapes:

        1) list[TagHistoryTag] — for single-path string, list[str], list[dict].
        2) str — for expression-binding-strings (passthrough).

        The gateway accepts a property-binding-expression
        string in place of the tag list, which the model preserves verbatim.

        Rules:
        - str that starts with '{' and ends with '}' -> passthrough as str
          (expression binding to a view/custom/parent property).
        - any other str -> wrap in [{"path": str}] (single tag path).
        - list -> coerce each element: dict passthrough, str wraps as
          {"path": str}.
        - None -> passthrough (let Pydantic raise the required-field error).
        - anything else -> loud-fail with example. Previously a single
          dict like `{"path": "x"}` (a common port-from-JSON mistake) fell
          through to a generic union-mismatch ValidationError; now the user
          gets an actionable message.
        """
        if isinstance(v, str):
            if v.startswith("{") and v.endswith("}"):
                return v  # expression-string passthrough
            return [{"path": v}]
        if isinstance(v, list):
            return [{"path": x} if isinstance(x, str) else x for x in v]
        if v is None:
            return v
        raise ValueError(
            f"`tags` must be str, list[str], list[{{'path': str}}], or an "
            f"expression-string (begins with '{{' and ends with '}}'); got "
            f"{type(v).__name__}. Example: tags='[default]Tanks/T01/Level' "
            "or tags=['[default]A', '[default]B'] or "
            "tags=[{'path': '[default]A'}, {'path': '[default]B'}]."
        )


# ----- TagHistoryBinding -----


class TagHistoryBinding(IgnitionBaseModel):
    """Tag-history binding — pulls historical samples for one or more tags.

    Discriminator: type: Literal["tag-history"] — WITH HYPHEN.

    Member of the Binding discriminated union (bindings/__init__.py).
    """
    type: Literal["tag-history"] = "tag-history"
    enabled: bool = True
    overlayOptOut: bool = False
    config: TagHistoryBindingConfig
    transforms: list["Transform"] = Field(default_factory=list)  # forward ref; resolved by model_rebuild() below

    @model_serializer(mode="wrap")
    def _strip_defaults(self, handler, _info):
        """Drop gateway-absent default keys. See bindings/_emit.py."""
        return strip_binding_defaults(self, handler, _info)


# Resolve `list["Transform"]` forward ref — same idiom as every other binding module.
TagHistoryBinding.model_rebuild()
