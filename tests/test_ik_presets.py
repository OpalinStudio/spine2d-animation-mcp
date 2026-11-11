"""Presets on IK rigs: an IK constraint overrides its bones' rotation keys,
so the presets must animate the IK targets (planted feet, no dead keys).
Plus the PSD conventions that make such rigs: forearm / shin segments,
free layers, bone groups."""

import math

import pytest
from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import Group, PixelLayer

from spine2d_mcp.pipeline import import_psd_to_spine
from spine2d_mcp.psd.parser import parse_psd
from spine2d_mcp.spine import analysis
from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine import format as fmt
from spine2d_mcp.spine import generators as gen
from spine2d_mcp.spine.builder import build
from spine2d_mcp.spine.pose import Pose

TRANSLATE = fmt.BONE_TIMELINES["translate"]

# A humanoid with knees and elbows (name, left, top, width, height), PSD coords.
SEGMENTED = [
    ("head", 160, 20, 80, 80), ("body", 150, 110, 100, 180),
    ("arm_left", 100, 120, 40, 75), ("forearm_left", 100, 195, 40, 70), ("hand_left", 95, 262, 40, 40),
    ("arm_right", 260, 120, 40, 75), ("lower_arm_right", 260, 195, 40, 70), ("hand_right", 265, 262, 40, 40),
    ("thigh_left", 150, 300, 45, 95), ("shin_left", 150, 395, 45, 90), ("foot_left", 150, 480, 70, 28),
    ("leg_right", 205, 300, 45, 95), ("calf_right", 205, 395, 45, 90), ("foot_right", 205, 480, 70, 28),
]


@pytest.fixture
def ik_rig(make_psd, tmp_path):
    res = import_psd_to_spine(make_psd(SEGMENTED), str(tmp_path / "rig"), ik_legs=True, ik_arms=True)
    return doc.load(res.project_path)


def test_segmented_limbs_get_real_two_bone_ik(ik_rig):
    parent = {b["name"]: b.get("parent") for b in ik_rig["bones"]}
    assert parent["shin_left"] == "leg_left" and parent["foot_left"] == "shin_left"
    assert parent["forearm_right"] == "arm_right" and parent["hand_right"] == "forearm_right"
    chains = {c["name"]: c for c in ik_rig["constraints"]}
    assert chains["shin_left-ik"]["bones"] == ["leg_left", "shin_left"]
    assert chains["forearm_right-ik"]["bones"] == ["arm_right", "forearm_right"]
    # Knees bend forward, elbows backward, for a character facing +x.
    assert chains["shin_left-ik"]["bendPositive"] is False
    assert chains["forearm_right-ik"].get("bendPositive", True) is True
    # The foot keeps its own angle while the shin swings.
    foot = doc.find_bone(ik_rig, "foot_left")
    assert foot["inherit"] == "noRotationOrReflection"
    assert Pose(ik_rig).bones["foot_left"].world_rotation == pytest.approx(-90)


def test_walk_on_ik_legs_plants_the_feet(ik_rig):
    res = gen.walk(ik_rig, duration=1.0)
    bones = ik_rig["animations"]["walk"]["bones"]
    assert not any("rotate" in bones.get(b, {}) for b in ("leg_left", "shin_left", "leg_right", "shin_right"))
    assert "dead_keys" not in {i["code"] for i in analysis.analyze(ik_rig, "walk")["issues"]}
    assert res["ik_targets_keyed"] == ["forearm_left-ik-target", "forearm_right-ik-target",
                                       "shin_left-ik-target", "shin_right-ik-target"]

    keys = bones["shin_left-ik-target"]["translate"]
    assert an.sample(TRANSLATE, keys, 0.0) == pytest.approx(an.sample(TRANSLATE, keys, 1.0), abs=1e-3)
    # Left foot: contact at 0.25, on the ground for 55 % of the cycle.
    stance = [an.sample(TRANSLATE, keys, 0.25 + 0.55 * i / 10) for i in range(11)]
    assert all(abs(y) < 1e-3 for _, y in stance)
    steps = [b[0] - a[0] for a, b in zip(stance, stance[1:])]
    assert all(s == pytest.approx(steps[0], rel=1e-3) for s in steps) and steps[0] < 0
    # ...and what the game must move the character by so it does not skate.
    assert res["planted_feet"]["ground_speed"] == pytest.approx(-steps[0] * 10 / 0.55, rel=1e-3)
    assert res["planted_feet"]["step_length"] == pytest.approx(stance[0][0] - stance[-1][0], rel=1e-3)
    # Swing: the foot leaves the ground and passes under the body.
    x, y = an.sample(TRANSLATE, keys, 0.025)
    assert y == pytest.approx(0.12 * 185, rel=0.02) and abs(x) < 1
    # The other foot does the same half a cycle later.
    other = bones["shin_right-ik-target"]["translate"]
    for t in (0.1, 0.4, 0.8):
        assert an.sample(TRANSLATE, other, (t + 0.5) % 1.0) == pytest.approx(
            an.sample(TRANSLATE, keys, t), abs=1e-2)


def test_walk_lowers_the_hip_so_the_legs_always_reach(ik_rig):
    gen.walk(ik_rig, duration=1.0, stride=30)
    for i in range(41):
        pose = Pose(ik_rig, "walk", i / 40)
        for side in ("left", "right"):
            hip, target = pose.bones[f"leg_{side}"], pose.bones[f"shin_{side}-ik-target"]
            assert math.hypot(target.worldX - hip.worldX, target.worldY - hip.worldY) <= 185.01


def test_presets_move_ik_arms_through_their_targets(ik_rig):
    res = gen.wave(ik_rig, side="right")
    bones = ik_rig["animations"]["wave"]["bones"]
    assert "arm_right" not in bones and "forearm_right" not in bones
    assert res["ik_targets_keyed"] == ["forearm_right-ik-target"]
    # The hand target ends up where the raised FK arm would have put the wrist.
    keys = bones["forearm_right-ik-target"]["translate"]
    setup = Pose(ik_rig).bones
    shoulder, wrist = setup["arm_right"], setup["forearm_right-ik-target"]
    x, y = an.sample(TRANSLATE, keys, 1.0)  # arm raised 150 deg, mid-wave
    reach = math.hypot(wrist.worldX - shoulder.worldX, wrist.worldY - shoulder.worldY)
    raised = math.hypot(wrist.worldX + x - shoulder.worldX, wrist.worldY + y - shoulder.worldY)
    assert raised == pytest.approx(reach, rel=0.2) and wrist.worldY + y > shoulder.worldY


def test_jump_on_ik_legs_squats_then_leaves_the_ground(ik_rig):
    gen.jump(ik_rig, duration=1.0, height=150)
    bones = ik_rig["animations"]["jump"]["bones"]
    keys = bones["shin_left-ik-target"]["translate"]
    assert an.sample(TRANSLATE, keys, 0.2)[1] == 0  # anticipation: feet planted, knees fold
    assert an.sample(TRANSLATE, keys, 0.55)[1] > 150  # apex: above the jump height (tucked)
    assert an.sample(TRANSLATE, keys, 0.8)[1] == 0  # landed
    assert "scale" in bones["torso"] and "scale" not in bones["hip"]


def test_squash_is_in_screen_axes_whatever_the_bone_direction():
    data = doc.new_skeleton()
    doc.add_bone(data, "flat", length=10)
    doc.add_bone(data, "up", rotation=90, length=10)
    assert gen.squash_scale(data, "flat", 1.25, 0.8) == {"x": 1.25, "y": 0.8}
    assert gen.squash_scale(data, "up", 1.25, 0.8) == {"x": 0.8, "y": 1.25}
    # A bounce lands squashed: wide and short on screen, for both bones.
    for bone in ("flat", "up"):
        gen.bounce(data, bone, name=bone)
        first = data["animations"][bone]["bones"][bone]["scale"][0]
        along, across = ("y", "x") if bone == "up" else ("x", "y")
        assert first[along] > 1 > first[across]


# -------------------------------------------------------------------- PSD
def _psd(tmp_path, build_layers):
    psd = PSDImage.new("RGBA", (400, 600), color=(0, 0, 0, 0))

    def layer(parent, name, left, top, w, h):
        px = PixelLayer.frompil(Image.new("RGBA", (w, h), (200, 80, 80, 255)), psd, name, top=top, left=left)
        parent.append(px)

    def group(parent, name):
        return Group.new(parent, name)

    build_layers(psd, layer, group)
    path = tmp_path / "art.psd"
    psd.save(path)
    return str(path)


def test_layers_that_are_not_body_parts_are_kept(tmp_path):
    def layers(psd, layer, group):
        layer(psd, "body", 150, 110, 100, 180)
        head = group(psd, "head")
        layer(head, "head", 160, 20, 80, 80)
        layer(head, "eye left", 170, 40, 20, 20)
        layer(psd, "sword", 300, 200, 20, 120)
        layer(psd, "guide [ignore]", 0, 0, 400, 600)

    result = build(parse_psd(_psd(tmp_path, layers)))
    bones = {b.name: b for b in result.project.bones}
    assert bones["eye_left"].parent == "head" and bones["sword"].parent == "root"
    assert "guide" not in bones and all("ignore" not in s.name for s in result.project.slots)
    assert [s.name for s in result.project.slots] == ["torso", "head", "eye_left", "sword"]
    # The eye stays where it was painted: bone at the layer center, image on the bone.
    assert (bones["eye_left"].x + bones["head"].x, result.project.skins[0].attachments["eye_left"]["eye_left"].x) \
        != (0, None)
    eye = result.project.skins[0].attachments["eye_left"]["eye_left"]
    assert (eye.x, eye.y, eye.width) == (0, 0, 20)
    assert set(result.images) == {"torso", "head", "eye_left", "sword"}


def test_psd_without_body_parts_imports_as_bones_per_layer(tmp_path):
    def layers(psd, layer, group):
        layer(psd, "fond", 0, 0, 400, 600)
        hero = group(psd, "perso [bone]")
        layer(hero, "corps", 100, 200, 200, 300)
        layer(hero, "chapeau", 150, 120, 100, 80)
        layer(psd, "perso[pivot]", 198, 498, 4, 4)

    res = import_psd_to_spine(_psd(tmp_path, layers), str(tmp_path / "out"), export_images=True)
    data = doc.load(res.project_path)
    parent = {b["name"]: b.get("parent") for b in data["bones"]}
    assert parent == {"root": None, "perso": "root", "corps": "perso", "chapeau": "perso", "fond": "root"}
    world = Pose(data).bones
    # The group bone sits on its [pivot] marker, the layers at their centers.
    assert (world["perso"].worldX, world["perso"].worldY) == pytest.approx((200, 100))
    assert (world["chapeau"].worldX, world["chapeau"].worldY) == pytest.approx((200, 440))
    assert doc.slot_names(data) == ["fond", "corps", "chapeau"]
    assert sorted(p.name for p in res.image_paths) == ["chapeau.png", "corps.png", "fond.png"]
    # The symbol presets animate the character group, not the background tile.
    assert gen.symbol_bone(data) == "root"
    assert "warnings" not in gen.symbol_win(data, bone="perso")
