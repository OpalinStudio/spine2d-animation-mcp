from spine2d_mcp.spine.schema import (
    Bone,
    IkConstraint,
    RegionAttachment,
    Skin,
    Slot,
    SpineProject,
)
from spine2d_mcp.spine.writer import to_dict


def test_defaults_are_stripped():
    """A bone with only a name must serialize to just {"name": ...} —
    the editor rejects redundant default fields."""
    proj = SpineProject(bones=[Bone(name="root")])
    out = to_dict(proj)
    assert out["bones"] == [{"name": "root"}]


def test_non_default_bone_fields_kept():
    proj = SpineProject(
        bones=[Bone(name="head", parent="body", x=10.0, rotation=90.0)]
    )
    bone = to_dict(proj)["bones"][0]
    assert bone == {"name": "head", "parent": "body", "x": 10.0, "rotation": 90.0}


def test_inherit_field_name():
    """4.2+ uses `inherit`, not `transform`."""
    from spine2d_mcp.spine.schema import Inherit

    proj = SpineProject(bones=[Bone(name="b", inherit=Inherit.noScale)])
    assert to_dict(proj)["bones"][0]["inherit"] == "noScale"


def test_region_attachment_required_dims():
    """width/height are required and always emitted even at default-looking
    values, because the reader reads them without a default."""
    att = RegionAttachment(width=64.0, height=128.0)
    proj = SpineProject(
        slots=[Slot(name="head", bone="head", attachment="head")],
        skins=[Skin(attachments={"head": {"head": att}})],
    )
    out = to_dict(proj)
    region = out["skins"][0]["attachments"]["head"]["head"]
    assert region == {"width": 64.0, "height": 128.0}


def test_ik_constraint_in_unified_constraints_array():
    """4.3 stores IK in `constraints` with a mandatory `type`, no `order`."""
    ik = IkConstraint(name="leg_ik", bones=["thigh", "shin"], target="foot")
    proj = SpineProject(constraints=[ik])
    data = to_dict(proj)
    assert "ik" not in data
    out = data["constraints"][0]
    assert out["type"] == "ik"
    assert "order" not in out
    assert out["name"] == "leg_ik"
    assert out["bones"] == ["thigh", "shin"]
    assert out["target"] == "foot"


def test_skeleton_version_present():
    out = to_dict(SpineProject())
    assert out["skeleton"]["spine"].startswith("4.3")


def test_default_skin_keeps_its_name():
    """The 4.3 reader requires skin `name` even for the default skin."""
    out = to_dict(SpineProject(skins=[Skin()]))
    assert out["skins"][0]["name"] == "default"


def test_roundtrip_through_json():
    proj = SpineProject(bones=[Bone(name="root"), Bone(name="body", parent="root")])
    reparsed = SpineProject.model_validate(to_dict(proj))
    assert [b.name for b in reparsed.bones] == ["root", "body"]
