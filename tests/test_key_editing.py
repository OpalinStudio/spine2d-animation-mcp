"""Key editing: loop-wrapped offsets (overlapping action), value scaling and
bone-to-bone copies must keep the motion's shape."""

import pytest

from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine import format as fmt
from spine2d_mcp.tools import animation as ta
from spine2d_mcp.tools import skeleton as ts

ROT = fmt.BONE_TIMELINES["rotate"]
TRANSLATE = fmt.BONE_TIMELINES["translate"]


def _loop_keys():
    anim: dict = {}
    an.set_keys(anim, "bone", "b", "rotate", [
        {"time": 0, "value": 0, "curve": "easeOutBack"},
        {"time": 0.3, "value": 40, "curve": "easeInOutSine"},
        {"time": 0.7, "value": -25, "curve": [0.2, 0.0, 0.4, 1.3]},
        {"time": 1.0, "value": 0},
    ])
    return anim["bones"]["b"]["rotate"]


@pytest.mark.parametrize("offset", [0.1, 0.3, 0.45, 0.85, -0.2, 1.25])
def test_wrapped_offset_is_the_same_motion_at_another_phase(offset):
    keys = _loop_keys()
    shifted = an.shift_keys(keys, ROT, offset, 1.0)
    assert an.key_time(shifted[0]) == 0 and an.key_time(shifted[-1]) == pytest.approx(1.0)
    for i in range(101):
        t = i / 100
        expected = an.sample(ROT, keys, (t - offset) % 1.0)[0]
        assert an.sample(ROT, shifted, t)[0] == pytest.approx(expected, abs=2e-3), t


def test_wrapped_offset_keeps_two_value_curves_and_holds():
    anim: dict = {}
    # First key after 0 and last key before the loop end: both are holds.
    an.set_keys(anim, "bone", "b", "translate", [
        {"time": 0.2, "x": 0, "y": 0, "curve": "easeOut"},
        {"time": 0.5, "x": 30, "y": -12, "curve": "easeIn"},
        {"time": 0.8, "x": 0, "y": 0},
    ])
    keys = anim["bones"]["b"]["translate"]
    shifted = an.shift_keys(keys, TRANSLATE, 0.35, 1.0)
    for i in range(51):
        t = i / 50
        src = (t - 0.35) % 1.0
        expected = an.sample(TRANSLATE, keys, min(max(src, 0.2), 0.8))
        assert an.sample(TRANSLATE, shifted, t) == pytest.approx(expected, abs=2e-3), t


def test_wrap_refuses_a_timeline_that_does_not_loop():
    keys = [{"value": 0}, {"time": 1.0, "value": 30}]
    with pytest.raises(an.AnimationError, match="does not loop"):
        an.shift_keys(keys, ROT, 0.2, 1.0)
    moved = an.shift_keys(keys, ROT, 0.2, 1.0, wrap=False)
    assert [an.key_time(k) for k in moved] == pytest.approx([0.2, 1.2])
    with pytest.raises(an.AnimationError, match="before 0"):
        an.shift_keys(keys, ROT, -0.5, 1.0, wrap=False)


def test_wrapped_stepped_timeline_keeps_the_state_across_the_loop_point():
    spec = fmt.SLOT_TIMELINES["attachment"]
    keys = [{"name": "open"}, {"time": 0.8, "name": "closed"}, {"time": 0.9, "name": "open"}]
    shifted = an.shift_keys(keys, spec, 0.15, 1.0)
    # The blink now straddles the loop point: closed at the very start.
    assert an.sample_stepped(shifted, 0.0)["name"] == "closed"
    assert an.sample_stepped(shifted, 0.06)["name"] == "open"
    assert an.sample_stepped(shifted, 0.96)["name"] == "closed"


def test_wrapped_deform_timeline_blends_vertices_at_the_cut():
    keys = [{"vertices": [0, 0, 0, 0]}, {"time": 0.5, "vertices": [10, 0, 0, 4]},
            {"time": 1.0, "vertices": [0, 0, 0, 0]}]
    shifted = an.shift_keys(keys, fmt.DEFORM_TIMELINE, 0.25, 1.0)
    assert [(an.key_time(k), k["vertices"]) for k in shifted] == [
        (0, [5, 0, 0, 2]), (0.25, [0, 0, 0, 0]), (0.75, [10, 0, 0, 4]), (1, [5, 0, 0, 2])]


def test_scale_values_amplifies_around_the_neutral_value():
    keys = _loop_keys()
    big = an.scale_values(ROT, keys, 1.5)
    for i in range(41):
        t = i / 40
        assert an.sample(ROT, big, t)[0] == pytest.approx(1.5 * an.sample(ROT, keys, t)[0], abs=1e-3)
    spec = fmt.BONE_TIMELINES["scale"]
    squash = [{"x": 1.2, "y": 0.8, "curve": "easeOut"}, {"time": 0.5, "x": 1, "y": 1}]
    anim: dict = {}
    squash = an.set_keys(anim, "bone", "b", "scale", squash)
    soft = an.scale_values(spec, squash, 0.5)
    assert (soft[0]["x"], soft[0]["y"]) == pytest.approx((1.1, 0.9))
    assert an.sample(spec, soft, 0.25) == pytest.approx(
        [1 + (v - 1) * 0.5 for v in an.sample(spec, squash, 0.25)], abs=1e-4)


@pytest.fixture
def arm(tmp_path):
    sk = str(tmp_path / "arm.json")
    ts.create_skeleton(sk)
    ts.add_bone(sk, "arm", length=50)
    ts.add_bone(sk, "forearm", "arm", x=50, length=40)
    ts.add_bone(sk, "hand", "forearm", x=40, length=15)
    ts.add_bone(sk, "arm_right", length=50)
    for b in ("arm", "forearm", "hand"):
        ta.set_keyframes(sk, "swing", "bone", b, [
            {"time": 0, "value": 0, "curve": "easeInOutSine"},
            {"time": 0.5, "value": 30, "curve": "easeInOutSine"},
            {"time": 1.0, "value": 0},
        ], timeline="rotate")
    return sk


def _peak_time(sk, bone):
    keys = doc.load(sk)["animations"]["swing"]["bones"][bone]["rotate"]
    return max(range(101), key=lambda i: an.sample(ROT, keys, i / 100)[0]) / 100


def test_offset_keys_stagger_makes_each_bone_trail_its_parent(arm):
    res = ta.offset_keys(arm, "swing", 0.0, bones=["arm", "forearm", "hand"], stagger=0.1)
    assert res["shifted"] == ["bone.forearm.rotate", "bone.hand.rotate"] and res["duration"] == 1.0
    assert [_peak_time(arm, b) for b in ("arm", "forearm", "hand")] == pytest.approx([0.5, 0.6, 0.7])


def test_copy_keys_mirrors_to_the_other_side_half_a_cycle_later(arm):
    ta.copy_keys(arm, "swing", {"arm": "arm_right"}, value_scale=-1, time_offset=0.5)
    bones = doc.load(arm)["animations"]["swing"]["bones"]
    for i in range(21):
        t = i / 20
        left = an.sample(ROT, bones["arm"]["rotate"], (t - 0.5) % 1.0)[0]
        assert an.sample(ROT, bones["arm_right"]["rotate"], t)[0] == pytest.approx(-left, abs=1e-3)


def test_scale_keys_tool_filters_bones_and_timelines(arm):
    ta.scale_keys(arm, "swing", 2.0, bones=["hand"], timelines=["rotate"])
    bones = doc.load(arm)["animations"]["swing"]["bones"]
    assert bones["hand"]["rotate"][1]["value"] == 60 and bones["arm"]["rotate"][1]["value"] == 30
    with pytest.raises(ValueError, match="no bone timeline matched"):
        ta.scale_keys(arm, "swing", 2.0, bones=["hand"], timelines=["translate"])
