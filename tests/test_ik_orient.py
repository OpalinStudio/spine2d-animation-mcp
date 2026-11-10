"""IK on a zero-length bone: Spine solves for the bone TIP, not its child.

`ik_for_chain(create_target=True)` used to place the target on the first
child of a zero-length last bone and say nothing: with 2-bone IK the elbow
then flies to the target (arm broken). It now warns, and
`orient_to_child=True` rotates/lengthens the bone toward the child while
keeping every child, attachment and weighted vertex where it was.
"""

import math

import pytest

from spine2d_mcp.spine import attachments as att
from spine2d_mcp.spine import constraints as cons
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine.pose import Pose
from spine2d_mcp.spine.validator import validate_data


def _arm(**forearm):
    """Shoulder -> upper arm (length 100) -> forearm (length 0, rotation 0)
    whose child `wrist` sits at (60, 80): the forearm does not point at it."""
    d = doc.new_skeleton()
    doc.add_bone(d, "shoulder", y=300)
    doc.add_bone(d, "upper", "shoulder", rotation=-60, length=100)
    doc.add_bone(d, "forearm", "upper", x=100, **forearm)
    doc.add_bone(d, "wrist", "forearm", x=60, y=80, rotation=15)
    doc.add_bone(d, "free", "forearm", x=10, y=-20, rotation=30, inherit="noRotationOrReflection")
    doc.add_slot(d, "forearm_img", "forearm", attachment="forearm_img")
    doc.set_attachment(d, "forearm_img", "forearm_img",
                       att.region(40, 120, x=30, y=40, rotation=5))
    doc.add_slot(d, "pt", "forearm", attachment="pt")
    doc.set_attachment(d, "pt", "pt", att.point(x=20, y=-10, rotation=12))
    return d


def _world(d, names):
    p = Pose(d)
    return {n: (p.bones[n].worldX, p.bones[n].worldY, p.bones[n].world_rotation) for n in names}


def _region_world(d, slot, name):
    p = Pose(d)
    a = doc.get_attachment(d, slot, name)
    b = p.bones[doc.find_slot(d, slot)["bone"]]
    x, y = b.local_to_world(a.get("x", 0), a.get("y", 0))
    return x, y, b.world_rotation + a.get("rotation", 0)


def test_zero_length_two_bone_ik_warns_by_default():
    d = _arm()
    res = cons.ik_for_chain(d, ["upper", "forearm"])
    assert res["warnings"] and "orient_to_child" in res["warnings"][0]
    assert doc.find_bone(d, "forearm").get("length", 0) == 0  # unchanged


def test_orient_to_child_points_the_bone_at_its_child_and_keeps_the_pose():
    d = _arm()
    names = ["shoulder", "upper", "forearm", "wrist", "free"]
    before = _world(d, names)
    region_before = _region_world(d, "forearm_img", "forearm_img")
    point_before = _region_world(d, "pt", "pt")

    res = cons.ik_for_chain(d, ["upper", "forearm"], orient_to_child=True)

    fa = doc.find_bone(d, "forearm")
    assert fa["length"] == pytest.approx(100.0, abs=1e-3)
    assert fa["rotation"] == pytest.approx(math.degrees(math.atan2(80, 60)), abs=1e-3)
    after = _world(d, names)
    for n in ("shoulder", "upper", "wrist", "free"):
        assert after[n][:2] == pytest.approx(before[n][:2], abs=1e-3), n
        assert after[n][2] == pytest.approx(before[n][2], abs=1e-3), n
    assert _region_world(d, "forearm_img", "forearm_img") == pytest.approx(region_before, abs=1e-3)
    assert _region_world(d, "pt", "pt") == pytest.approx(point_before, abs=1e-3)
    # The target is at the bone tip, which is now the wrist.
    p = Pose(d)
    t = p.bones[res["target_bone"]]
    assert (t.worldX, t.worldY) == pytest.approx(p.bones["forearm"].tip, abs=1e-3)
    assert (t.worldX, t.worldY) == pytest.approx(after["wrist"][:2], abs=1e-3)
    assert not res["warnings"]
    assert validate_data(d).ok


def test_orient_keeps_unweighted_and_weighted_vertices():
    d = _arm()
    mesh = att.mesh(uvs=[0, 0, 1, 0, 1, 1, 0, 1], triangles=[0, 1, 2, 0, 2, 3],
                    vertices=[0, 0, 50, 0, 50, 50, 0, 50])
    doc.set_attachment(d, "forearm_img", "m", mesh)
    fi = doc.bone_index(d, "forearm")
    ui = doc.bone_index(d, "upper")
    # One weighted vertex: half on upper, half on forearm.
    w = {"type": "boundingbox", "vertexCount": 1,
         "vertices": [2, ui, 5, 6, 0.5, fi, 7, 8, 0.5]}
    doc.set_attachment(d, "forearm_img", "w", w)
    p0 = Pose(d)
    fb0 = p0.bones["forearm"]
    mesh_world0 = [fb0.local_to_world(*v) for v in [(0, 0), (50, 0), (50, 50), (0, 50)]]
    wv0 = p0.bones["forearm"].local_to_world(7, 8)

    cons.ik_for_chain(d, ["upper", "forearm"], orient_to_child=True)

    p1 = Pose(d)
    fb1 = p1.bones["forearm"]
    m = doc.get_attachment(d, "forearm_img", "m")["vertices"]
    mesh_world1 = [fb1.local_to_world(m[i], m[i + 1]) for i in range(0, len(m), 2)]
    for a, b in zip(mesh_world0, mesh_world1):
        assert a == pytest.approx(b, abs=1e-3)
    v = doc.get_attachment(d, "forearm_img", "w")["vertices"]
    assert v[1] == ui and (v[2], v[3]) == (5, 6)  # other bone untouched
    assert fb1.local_to_world(v[6], v[7]) == pytest.approx(wv0, abs=1e-3)


def test_orient_refuses_non_uniform_scale_or_shear():
    d = _arm(scaleX=1.5)
    with pytest.raises(cons.ConstraintError):
        cons.ik_for_chain(d, ["upper", "forearm"], orient_to_child=True)


def test_orient_warns_about_child_translate_keys():
    d = _arm()
    d["animations"] = {"a": {"bones": {"wrist": {"translate": [{"x": 5}]}}}}
    res = cons.ik_for_chain(d, ["upper", "forearm"], orient_to_child=True)
    assert any("wrist" in w and "translate" in w for w in res["warnings"])


def test_bone_with_length_is_unchanged_and_silent():
    d = _arm(length=90)
    res = cons.ik_for_chain(d, ["upper", "forearm"], orient_to_child=True)
    assert doc.find_bone(d, "forearm").get("rotation", 0) == 0
    assert not res["warnings"]


def test_tool_returns_warnings_and_orients(tmp_path):
    from spine2d_mcp.tools import skeleton as sk

    j = tmp_path / "arm.json"
    doc.save(_arm(), j)
    res = sk.add_ik_constraint(str(j), ["upper", "forearm"], create_target=True)
    assert any("orient_to_child" in w for w in res["warnings"])
    doc.save(_arm(), j)
    res = sk.add_ik_constraint(str(j), ["upper", "forearm"], create_target=True,
                               orient_to_child=True)
    assert not any("orient_to_child" in w for w in res.get("warnings", []))
    assert doc.find_bone(doc.load(j), "forearm")["length"] == pytest.approx(100, abs=1e-3)
