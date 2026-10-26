"""Skeleton editing: references, weighted vertex remapping, draw order."""

import itertools
import random

import pytest

from spine2d_mcp.spine import attachments as att
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine.pose import Pose
from spine2d_mcp.spine.validator import validate_data


def _rig():
    d = doc.new_skeleton(200, 300)
    doc.add_bone(d, "hip", "root", y=100)
    doc.add_bone(d, "torso", "hip", length=80, rotation=90)
    doc.add_bone(d, "head", "torso", x=80, length=40)
    doc.add_bone(d, "tail1", "hip", x=-10, length=30, rotation=180)
    doc.add_bone(d, "tail2", "tail1", x=30, length=30)
    for s, b in (("body", "torso"), ("head", "head"), ("tail", "tail1")):
        doc.add_slot(d, s, b, attachment=s)
        doc.set_attachment(d, s, s, att.region(50, 50))
    return d


def test_new_skeleton_is_valid_43():
    d = doc.new_skeleton()
    assert d["skeleton"]["spine"].startswith("4.3")
    assert validate_data(d).ok


def test_add_bone_keeps_parent_before_child_and_subtree_grouping():
    d = _rig()
    doc.add_bone(d, "jaw", "head")
    names = [b["name"] for b in d["bones"]]
    assert names.index("jaw") == names.index("head") + 1
    assert validate_data(d).ok


def test_rename_bone_updates_every_reference():
    d = _rig()
    doc.add_constraint(d, {"type": "ik", "name": "k", "bones": ["head"], "target": "tail2"})
    d["animations"]["a"] = {"bones": {"head": {"rotate": [{"value": 5}]}}}
    doc.rename_bone(d, "head", "skull")
    assert doc.find_slot(d, "head")["bone"] == "skull"
    assert d["constraints"][0]["bones"] == ["skull"]
    assert "skull" in d["animations"]["a"]["bones"]
    assert validate_data(d).ok


def test_remove_bone_cascades():
    d = _rig()
    doc.add_constraint(d, {"type": "physics", "name": "p", "bone": "tail2", "rotate": 1})
    d["animations"]["wag"] = {"bones": {"tail2": {"rotate": [{"value": 5}]}}}
    res = doc.remove_bone(d, "tail1")
    assert res["removed_bones"] == ["tail1", "tail2"]
    assert res["removed_slots"] == ["tail"]
    assert "constraints" not in d
    assert "wag" in d["animations"] and not d["animations"]["wag"]
    assert validate_data(d).ok


def test_weighted_vertex_indices_follow_bone_insertions_and_removals():
    d = _rig()
    mesh = att.grid_mesh(40, 60, 1, 2)
    mesh["vertices"] = att.auto_weights(d, "tail", mesh, ["tail1", "tail2"])
    doc.set_attachment(d, "tail", "tail", mesh)
    before = Pose(d)
    # Inserting a bone early in the list shifts indices of later bones.
    doc.add_bone(d, "hip2", "hip")
    doc.remove_bone(d, "head")
    assert validate_data(d).ok
    names = [b["name"] for b in d["bones"]]
    v = doc.get_attachment(d, "tail", "tail")["vertices"]
    used = set()
    i = 0
    while i < len(v):
        n = int(v[i]); i += 1
        for _ in range(n):
            used.add(names[int(v[i])]); i += 4
    assert used <= {"tail1", "tail2"}
    after = Pose(d)
    assert after.bones["tail2"].worldX == pytest.approx(before.bones["tail2"].worldX)


def test_remove_bone_refuses_when_mesh_weights_depend_on_it():
    d = _rig()
    mesh = att.grid_mesh(40, 60, 1, 1)
    doc.set_attachment(d, "body", "mesh", mesh)
    mesh["vertices"] = att.auto_weights(d, "body", mesh, ["torso", "tail2"])
    with pytest.raises(doc.SpineEditError, match="re-weight"):
        doc.remove_bone(d, "tail2")


def test_reparent_keep_world_position():
    d = _rig()
    world = Pose(d).bones["head"]
    doc.reparent_bone(d, "head", "tail2", keep_world=True)
    after = Pose(d).bones["head"]
    assert (after.worldX, after.worldY) == pytest.approx((world.worldX, world.worldY), abs=1e-3)
    assert after.world_rotation == pytest.approx(world.world_rotation, abs=1e-3)
    names = [b["name"] for b in d["bones"]]
    assert names.index("tail2") < names.index("head")
    assert validate_data(d).ok


@pytest.mark.parametrize("seed", range(20))
def test_draw_order_encode_decode_roundtrip(seed):
    rnd = random.Random(seed)
    setup = [f"s{i}" for i in range(rnd.randint(2, 9))]
    order = setup[:]
    rnd.shuffle(order)
    offsets = doc.encode_draw_order(order, setup)
    key = {"offsets": offsets} if offsets else {}
    assert doc.decode_draw_order(key, setup) == order


def test_all_permutations_of_four_roundtrip():
    setup = list("abcd")
    for perm in itertools.permutations(setup):
        offsets = doc.encode_draw_order(list(perm), setup)
        assert doc.decode_draw_order({"offsets": offsets} if offsets else {}, setup) == list(perm)


def test_setup_order_change_reencodes_draw_order_keys():
    d = _rig()
    from spine2d_mcp.spine.animation import set_draw_order_keys

    anim = d["animations"].setdefault("swap", {})
    set_draw_order_keys(anim, doc.slot_names(d), [{"time": 0.5, "order": ["head", "body", "tail"]}])
    wanted = doc.decode_draw_order(anim["drawOrder"][0], doc.slot_names(d))
    doc.set_setup_draw_order(d, ["tail", "head", "body"])
    assert doc.decode_draw_order(anim["drawOrder"][0], doc.slot_names(d)) == wanted
    doc.add_slot(d, "fx", "root", index=1)
    got = doc.decode_draw_order(anim["drawOrder"][0], doc.slot_names(d))
    assert [s for s in got if s != "fx"] == wanted
    assert validate_data(d).ok


def test_rename_slot_and_skin_and_constraint():
    d = _rig()
    doc.add_skin(d, "red")
    doc.set_attachment(d, "head", "head", att.region(10, 10), skin="red")
    doc.add_constraint(d, {"type": "transform", "name": "t", "source": "hip", "bones": ["head"],
                           "properties": {"rotate": {"to": {"rotate": {}}}}})
    doc.update_skin(d, "red", add_constraints=[{"name": "t", "type": "transform"}])
    d["animations"]["a"] = {"slots": {"head": {"alpha": [{"value": 0.5}]}},
                            "transform": {"t": [{"mixRotate": 0.5}]},
                            "attachments": {"red": {"head": {"head": {"sequence": [{}]}}}}}
    doc.rename_slot(d, "head", "face")
    doc.rename_skin(d, "red", "blue")
    doc.rename_constraint(d, "t", "follow")
    a = d["animations"]["a"]
    assert "face" in a["slots"] and "follow" in a["transform"] and "blue" in a["attachments"]
    assert doc.find_skin(d, "blue")["transform"] == ["follow"]
    assert validate_data(d).ok


def test_edit_rejects_invalid_result(tmp_path):
    d = _rig()
    p = tmp_path / "s.json"
    doc.save(d, p)
    d["slots"][0]["bone"] = "ghost"
    with pytest.raises(doc.SpineEditError):
        doc.save(d, p)
    assert doc.load(p)["slots"][0]["bone"] == "torso"
