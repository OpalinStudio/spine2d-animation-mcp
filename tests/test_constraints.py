"""4.3 constraint builders and rig helpers."""

import pytest

from spine2d_mcp.spine import constraints as cons
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine.pose import Pose
from spine2d_mcp.spine.validator import validate_data


def _leg():
    d = doc.new_skeleton()
    doc.add_bone(d, "hip", y=200)
    doc.add_bone(d, "thigh", "hip", rotation=-90, length=100)
    doc.add_bone(d, "shin", "thigh", x=100, length=90)
    return d


def test_ik_defaults_are_omitted_and_scale_y_mode():
    c = cons.ik("leg", ["thigh", "shin"], "t", stretch=True, scale_y="volume", bend_positive=False)
    assert c == {"type": "ik", "name": "leg", "bones": ["thigh", "shin"], "target": "t",
                 "scaleY": "volume", "bendPositive": False, "stretch": True}
    assert "scaleY" not in cons.ik("x", ["a"], "b", scale_y="none")


def test_ik_for_chain_places_target_at_tip():
    d = _leg()
    res = cons.ik_for_chain(d, ["thigh", "shin"])
    pose = Pose(d)
    tip = pose.bones["shin"].tip
    t = pose.bones[res["target_bone"]]
    assert (t.worldX, t.worldY) == pytest.approx(tip, abs=1e-3)
    assert d["constraints"][0]["type"] == "ik"
    assert validate_data(d).ok


def test_transform_identity_mapping_and_mixes():
    c = cons.transform("t", "src", ["a"], copy=("rotate", "x", "y"), mix_x=0.5)
    assert c["properties"] == {"rotate": {"to": {"rotate": {}}}, "x": {"to": {"x": {}}}, "y": {"to": {"y": {}}}}
    assert c["mixX"] == 0.5 and "mixY" not in c  # mixY defaults to mixX
    assert "mixScaleX" not in c


def test_transform_cross_property_mapping():
    c = cons.transform("t", "src", ["a"], properties={"rotate": {"to": {"scaleY": {"scale": 0.01, "max": 2}}}},
                       clamp=True, local_source=True)
    assert c["properties"]["rotate"]["to"]["scaleY"] == {"scale": 0.01, "max": 2}
    assert c["clamp"] and c["localSource"]
    with pytest.raises(cons.ConstraintError):
        cons.transform("t", "s", ["a"], properties={"rotation": {"to": {"x": {}}}})


def test_physics_and_chain():
    d = _leg()
    out = cons.physics_chain(d, ["thigh", "shin"], gravity=50, scale_y="volume", scale_x=0.5)
    assert [c["name"] for c in out] == ["thigh-physics", "shin-physics"]
    assert out[1]["strength"] < 100 and out[1]["inertia"] > 0.5
    assert out[0]["scaleY"] == "volume"
    assert validate_data(d).ok
    g = cons.physics("p", "b", rotate=1, global_=("wind", "gravity"))
    assert g["windGlobal"] and g["gravityGlobal"]


def test_slider_bone_driven_and_manual():
    s = cons.slider("smile", "smile-pose", bone="ctrl", property="y", scale=0.02, local=True)
    assert s == {"type": "slider", "name": "smile", "animation": "smile-pose", "bone": "ctrl",
                 "property": "y", "scale": 0.02, "local": True}
    m = cons.slider("blend", "pose", time=0.5, loop=True)
    assert m["time"] == 0.5 and m["loop"] and "bone" not in m
    with pytest.raises(cons.ConstraintError):
        cons.slider("x", "a", bone="b", property="rotation")


def test_validator_catches_43_mistakes():
    d = _leg()
    d["constraints"] = [
        {"type": "transform", "name": "t", "target": "hip", "bones": ["thigh"]},
        {"type": "slider", "name": "s", "animation": "missing"},
    ]
    d["ik"] = []
    errors = " | ".join(validate_data(d).errors)
    assert "4.2 layout" in errors
    assert "`source`" in errors
    assert "slider animation 'missing' not found" in errors
