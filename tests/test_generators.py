"""Procedural presets produce valid, looping, editable animations."""

import pytest

from spine2d_mcp.pipeline import import_psd_to_spine
from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine import format as fmt
from spine2d_mcp.spine import generators as gen
from spine2d_mcp.spine.validator import validate_data


@pytest.fixture
def rig(synthetic_psd, tmp_path):
    res = import_psd_to_spine(synthetic_psd, str(tmp_path / "out"), orient_bones=True)
    return doc.load(res.project_path)


@pytest.mark.parametrize("preset", ["idle", "walk", "run"])
def test_cycles_loop_seamlessly(rig, preset):
    info = getattr(gen, preset)(rig)
    anim = rig["animations"][preset]
    assert info["keyed"]
    dur = an.animation_duration(anim)
    for bone, tls in anim["bones"].items():
        for tl, keys in tls.items():
            spec = fmt.BONE_TIMELINES[tl]
            assert an.sample(spec, keys, 0) == pytest.approx(an.sample(spec, keys, dur), abs=1e-3), (bone, tl)
    assert validate_data(rig).ok


@pytest.mark.parametrize("fn,kw", [
    (gen.jump, {}),
    (gen.wave, {"side": "left"}),
    (gen.head_motion, {"kind": "shake"}),
    (gen.head_motion, {"kind": "tilt"}),
    (gen.hover, {"bone": "head"}),
    (gen.bounce, {"bone": "hip", "bounces": 2}),
    (gen.shake, {"bone": "root"}),
])
def test_presets_validate(rig, fn, kw):
    fn(rig, **kw)
    assert validate_data(rig).ok


def test_follow_through_delays_each_bone(rig):
    gen.follow_through(rig, "wag", ["arm_left", "hand_left"], amplitude=10, period=1, delay=90)
    a = rig["animations"]["wag"]["bones"]
    spec = fmt.BONE_TIMELINES["rotate"]
    v_arm = an.sample(spec, a["arm_left"]["rotate"], 0.25)[0]
    v_hand = an.sample(spec, a["hand_left"]["rotate"], 0.5)[0]
    assert v_arm == pytest.approx(v_hand, abs=0.3)


def test_color_effects(rig):
    gen.color_effect(rig, ["head"], "hit", "flash", times=2)
    gen.color_effect(rig, ["torso"], "hit", "pulse", times=3)
    gen.color_effect(rig, ["arm_left"], "hit", "tint", color="ff0000")
    assert doc.find_slot(rig, "head")["dark"] == "000000"  # tint black enabled
    assert validate_data(rig).ok


def test_blink_with_attachment_swap(rig):
    from spine2d_mcp.spine import attachments as att

    doc.set_attachment(rig, "head", "head-closed", att.region(80, 80))
    gen.blink(rig, slot="head", closed_attachment="head-closed")
    keys = rig["animations"]["blink"]["slots"]["head"]["attachment"]
    assert [k["name"] for k in keys] == ["head", "head-closed", "head"]
    assert validate_data(rig).ok


def test_roles_override(rig):
    with pytest.raises(gen.AnimationError):
        gen.resolve_roles(rig, {"head": "nope"})
    r = gen.resolve_roles(rig, {"tail": "hand_left"})
    assert r["tail"] == "hand_left" and r["leg_left"] == "leg_left"


def test_psd_pipeline_with_ik_and_presets(synthetic_psd, tmp_path):
    res = import_psd_to_spine(synthetic_psd, str(tmp_path / "o"), ik_legs=True, export_images=True,
                              animations=["idle", "walk", "blink"])
    d = doc.load(res.project_path)
    assert {c["name"] for c in d["constraints"]} == {"foot_left-ik", "foot_right-ik"}
    assert "blink" not in res.animations  # synthetic rig has no eyes -> skipped
    assert {"idle", "walk"} <= set(res.animations)
    assert d["skeleton"]["images"] == "./images/"
    assert (tmp_path / "o" / "images" / "head.png").exists()
    assert validate_data(d).ok
