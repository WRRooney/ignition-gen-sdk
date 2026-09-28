"""PermissionSet / SecurityLevel: the shape shared by tags, UDT instances, providers and gateway security."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ignition_gen_sdk import PermissionSet, SecurityLevel, Tag, TagBuilder, UdtInstance
from ignition_gen_sdk.cli import app
from ignition_gen_sdk.models.tag_provider import TagProviderConfig
from ignition_gen_sdk.models.tags.tag import UdtMemberTag
from ignition_gen_sdk.serializers.udt_disk import udts_to_disk

# Verbatim from a gateway: security-properties writePermissions.
GATEWAY_WRITE = {
    "securityLevels": [
        {
            "children": [
                {
                    "children": [
                        {
                            "children": [],
                            "description": "System generated security level representing read and write privileges to Gateway configuration",
                            "name": "Administrator",
                        }
                    ],
                    "description": "Represents the roles that a user has.",
                    "name": "Roles",
                }
            ],
            "description": "Represents a user who has been authenticated by the system.",
            "name": "Authenticated",
        },
        {"children": [{"children": [], "name": "Write"}], "name": "APIKey"},
    ],
    "type": "AnyOf",
}


def test_round_trips_gateway_shape_byte_for_byte():
    ps = PermissionSet.model_validate(GATEWAY_WRITE)
    assert ps.emit() == GATEWAY_WRITE
    assert ps.paths() == ["Authenticated/Roles/Administrator", "APIKey/Write"]


def test_from_paths_merges_shared_prefixes():
    ps = PermissionSet.any_of("Authenticated/Roles/Operator", "Authenticated/Roles/Administrator", "APIKey/Write")
    assert ps.emit() == {
        "type": "AnyOf",
        "securityLevels": [
            {"name": "Authenticated", "children": [{"name": "Roles", "children": [
                {"name": "Operator", "children": []},
                {"name": "Administrator", "children": []},
            ]}]},
            {"name": "APIKey", "children": [{"name": "Write", "children": []}]},
        ],
    }
    assert PermissionSet.all_of("Authenticated").type == "AllOf"
    assert PermissionSet.everyone().is_open() and PermissionSet.everyone().emit() == {"type": "AnyOf", "securityLevels": []}


def test_type_is_constrained():
    with pytest.raises(ValidationError):
        PermissionSet.model_validate({"type": "OneOf", "securityLevels": []})
    with pytest.raises(ValidationError):
        SecurityLevel.model_validate({"name": "X", "level": 1})  # unknown key


def test_tag_carries_read_and_write_permissions():
    tag = (
        TagBuilder().name("Setpoint").datatype("Float8").memory().value(0.0)
        .permissions(write=PermissionSet.any_of("Authenticated/Roles/Operator"))
        .build()
    )
    out = tag.emit()
    assert out["writePermissions"]["securityLevels"][0]["name"] == "Authenticated"
    assert "readPermissions" not in out  # absent stays absent


def test_udt_instance_and_member_permissions_emit_to_disk():
    inst = UdtInstance(
        name="P01", typeId="Pump",
        readPermissions=PermissionSet.any_of("Authenticated"),
        tags=[UdtMemberTag(name="Run", tagType="AtomicTag", writePermissions=PermissionSet.any_of("Authenticated/Roles/Operator"))],
    )
    disk = udts_to_disk([inst])[0]
    assert disk["readPermissions"] == {"type": "AnyOf", "securityLevels": [{"name": "Authenticated", "children": []}]}
    assert disk["tags"][0]["writePermissions"]["securityLevels"][0]["children"][0]["children"][0]["name"] == "Operator"
    # a member permission may also be bound to a UDT parameter
    bound = UdtMemberTag(name="Run", tagType="AtomicTag", readPermissions={"bindType": "parameter", "binding": "{Perms}"})
    assert bound.emit()["readPermissions"]["bindType"] == "parameter"
    plain = Tag.model_validate({"name": "T", "tagType": "AtomicTag", "dataType": "Int4", "valueSource": "memory",
                               "readPermissions": GATEWAY_WRITE})
    assert plain.readPermissions.paths() == ["Authenticated/Roles/Administrator", "APIKey/Write"]


def test_provider_config_validates_permission_blocks(tmp_path):
    good = {"profile": {"type": "STANDARD", "allowBackfill": False, "enableTagReferenceStore": True},
            "settings": {"defaultDatasourceName": None, "readOnly": False, "valuePersistence": "Configuration",
                         "editPermissions": {"type": "AnyOf", "securityLevels": []},
                         "readPermissions": {"type": "AllOf", "securityLevels": []},
                         "writePermissions": GATEWAY_WRITE, "someFutureKey": 1}}
    cfg = TagProviderConfig.model_validate(good)
    assert cfg.settings.writePermissions.paths() == ["Authenticated/Roles/Administrator", "APIKey/Write"]
    bad = json.loads(json.dumps(good)); bad["settings"]["writePermissions"]["type"] = "Anyone"
    with pytest.raises(ValidationError):
        TagProviderConfig.model_validate(bad)
    f = tmp_path / "prov.json"; f.write_text(json.dumps(bad))
    result = CliRunner().invoke(app, ["provider", "create", "--name", "Plant", "--config-file", str(f), "--dry-run"])
    assert result.exit_code == 1 and "not a valid tag-provider config" in result.output + (result.stderr or "")
