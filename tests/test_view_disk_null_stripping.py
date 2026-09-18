"""view_to_disk strips nulls the Designer strips — and only those.

A null inside position/props is an unset layout/style value the Designer
deletes on save; emitting it produces a phantom diff on every round-trip.
A null anywhere else is a DECLARED property with no value yet, and dropping
the key would drop the declaration.
"""
from ignition_gen_sdk.backends.project_disk import dumps_designer
from ignition_gen_sdk.models.views.view import View


def _view(root: dict) -> dict:
    return View.model_validate(
        {
            "custom": {"unset": None},
            "params": {"tagPath": None},
            "props": {"defaultSize": {"width": 100}},
            "root": root,
        }
    ).model_dump(exclude_none=True, mode="json")


def test_position_and_props_nulls_are_dropped_declarations_are_kept() -> None:
    from ignition_gen_sdk.serializers.view_disk import _sorted_keys

    emitted = _sorted_keys(
        _view(
            {
                "meta": {"name": "root"},
                "type": "ia.container.flex",
                "children": [
                    {
                        "meta": {"name": "Child"},
                        "type": "ia.display.label",
                        "position": {"basis": None, "grow": 1},
                        "props": {"direction": None, "text": "hi"},
                    }
                ],
            }
        )
    )

    child = emitted["root"]["children"][0]
    assert child["position"] == {"grow": 1}, "unset position keys must go"
    assert child["props"] == {"text": "hi"}, "unset props keys must go"

    # Declared-but-empty properties keep their keys, or the declaration is lost.
    assert emitted["params"] == {"tagPath": None}
    assert emitted["custom"] == {"unset": None}


def test_dumps_designer_escapes_like_gson() -> None:
    text = dumps_designer({"expr": "if({a} = 1, 'x', \"y\") && b > c & d < e"})
    for raw in ("=", "'", ">", "<", "&"):
        assert raw not in text.split('"expr"')[1], f"{raw!r} left unescaped"
    for esc in ("\\u003d", "\\u0027", "\\u003e", "\\u003c", "\\u0026"):
        assert esc in text
    # Escaping must be lossless.
    import json

    assert json.loads(text)["expr"] == "if({a} = 1, 'x', \"y\") && b > c & d < e"


if __name__ == "__main__":
    test_position_and_props_nulls_are_dropped_declarations_are_kept()
    test_dumps_designer_escapes_like_gson()
    print("ok")
