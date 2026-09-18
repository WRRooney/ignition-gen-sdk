"""MapTransform keeps Designer-authored booleans as booleans.

Ground truth: IndustryPack-Water `PeristalticPump` gates each appearance
variant with a map transform on `position.display` —
`{"input": "p&id", "output": true}`, `fallback: false`. Before the union
listed `bool`, Pydantic's lax int path re-emitted those as `1` / `0`.
"""
from __future__ import annotations

from ignition_gen_sdk.transforms.map import MapMapping, MapTransform


def test_map_bool_output_and_fallback_round_trip_as_bool():
    mt = MapTransform.model_validate(
        {
            "type": "map",
            "inputType": "scalar",
            "outputType": "scalar",
            "mappings": [{"input": "p&id", "output": True}, {"input": False, "output": "x"}],
            "fallback": False,
        }
    )
    out = mt.model_dump(exclude_none=True, mode="json")
    assert out["mappings"][0]["output"] is True
    assert out["mappings"][1]["input"] is False
    assert out["fallback"] is False


def test_map_numeric_inputs_stay_numeric():
    m = MapMapping(input=1, output=2.5)
    out = m.model_dump(exclude_none=True, mode="json")
    assert out == {"input": 1, "output": 2.5}
    assert type(out["input"]) is int
