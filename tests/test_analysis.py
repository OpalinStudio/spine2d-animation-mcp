"""Animation review: each check must fire on the defect it names and stay
quiet on a clean animation."""

import math

import pytest

from spine2d_mcp.spine import analysis
from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import constraints as cons
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine import generators as gen


@pytest.fixture
def rig():
    data = doc.new_skeleton()
    doc.add_bone(data, "hip", y=100)
    doc.add_bone(data, "arm_left", "hip", length=40)
    doc.add_bone(data, "forearm_left", "arm_left", x=40, length=30)
    doc.add_bone(data, "hand_left", "forearm_left", x=30, length=10)
    doc.add_bone(data, "arm_right", "hip", length=40)
    doc.add_bone(data, "leg", "hip", rotation=-90, length=50)
    doc.add_bone(data, "shin", "leg", x=50, length=50)
    return data


def _codes(report):
    return {i["code"] for i in report["issues"]}


def _key(data, anim, bone, keys, timeline="rotate"):
    an.set_keys(doc.animations(data).setdefault(anim, {}), "bone", bone, timeline, keys)


def test_clean_eased_loop_has_no_issue(rig):
    gen.oscillate(rig, "sway", "hip", "rotate", amplitude=5, period=2)
    rep = analysis.analyze(rig, "sway")
    assert rep["loop"] == {"assumed": True, "auto_detected": True}
    assert rep["issues"] == [] and rep["duration"] == 2


def test_loop_pop_and_hitch(rig):
    _key(rig, "pop", "hip", [{"value": 0, "curve": "easeInOut"}, {"time": 1, "value": 20}])
    assert "loop_pop" in _codes(analysis.analyze(rig, "pop", loop=True))
    assert "loop_pop" not in _codes(analysis.analyze(rig, "pop", loop=False))
    # Ends flat, restarts at full speed: a tick at the seam.
    _key(rig, "hitch", "hip", [{"value": 0}, {"time": 0.5, "value": 20, "curve": "easeOut"},
                               {"time": 1, "value": 0}])
    assert "loop_hitch" in _codes(analysis.analyze(rig, "hitch", loop=True))


def test_linear_motion_is_reported_until_keys_get_curves(rig):
    keys = [{"value": 0}, {"time": 0.2, "value": 30}, {"time": 0.5, "value": -10}, {"time": 1, "value": 0}]
    _key(rig, "robot", "hip", keys)
    issue = next(i for i in analysis.analyze(rig, "robot")["issues"] if i["code"] == "linear_motion")
    assert issue["severity"] == "warning" and "hip.rotate (3)" in issue["where"]
    _key(rig, "robot", "hip", [{**k, "curve": "easeInOut"} for k in keys])
    assert "linear_motion" not in _codes(analysis.analyze(rig, "robot"))


def test_dead_keys_under_ik_unless_the_mix_is_keyed_down(rig):
    cons.ik_for_chain(rig, ["leg", "shin"])
    _key(rig, "kick", "leg", [{"value": 0, "curve": "easeOut"}, {"time": 0.3, "value": 40}])
    issue = next(i for i in analysis.analyze(rig, "kick")["issues"] if i["code"] == "dead_keys")
    assert "leg.rotate" in issue["where"] and "shin-ik-target" in issue["fix"]
    an.set_keys(rig["animations"]["kick"], "ik", "shin-ik", None, [{"mix": 0}])
    assert "dead_keys" not in _codes(analysis.analyze(rig, "kick"))


def test_twinning_needs_identical_sides(rig):
    keys = [{"value": 0, "curve": "easeInOut"}, {"time": 0.4, "value": 50, "curve": "easeInOut"},
            {"time": 1, "value": 0}]
    _key(rig, "cheer", "arm_left", keys)
    _key(rig, "cheer", "arm_right", keys)
    assert "twinning" in _codes(analysis.analyze(rig, "cheer"))
    _key(rig, "cheer", "arm_right", [{**k, "value": -k["value"]} for k in keys])
    assert "twinning" not in _codes(analysis.analyze(rig, "cheer"))


def test_chain_keyed_on_the_same_frames_has_no_overlap(rig):
    keys = [{"value": 0, "curve": "easeInOut"}, {"time": 0.5, "value": 30, "curve": "easeInOut"},
            {"time": 1, "value": 0}]
    for b in ("arm_left", "forearm_left", "hand_left"):
        _key(rig, "swing", b, keys)
    issue = next(i for i in analysis.analyze(rig, "swing")["issues"] if i["code"] == "no_overlap")
    assert issue["where"] == "arm_left > forearm_left > hand_left"
    anim = rig["animations"]["swing"]["bones"]
    for i, b in enumerate(("forearm_left", "hand_left"), 1):
        anim[b]["rotate"] = an.shift_keys(anim[b]["rotate"], an.spec_for("bone", "rotate"), 0.05 * i, 1.0)
    assert "no_overlap" not in _codes(analysis.analyze(rig, "swing"))


def test_squash_without_volume(rig):
    _key(rig, "squash", "hip", [{"x": 1, "y": 1, "curve": "easeOut"}, {"time": 0.2, "x": 1.5, "y": 0.9},
                                {"time": 0.5, "x": 1, "y": 1}], timeline="scale")
    assert "squash_volume" in _codes(analysis.analyze(rig, "squash"))
    _key(rig, "squash", "hip", [{"time": 0.2, "x": 1.25, "y": 0.8, "curve": "easeOut"}], timeline="scale")
    assert "squash_volume" not in _codes(analysis.analyze(rig, "squash"))


# ----------------------------------------------------------------- motion
def _sampled(tracks, n=61, duration=1.0):
    times = [duration * i / (n - 1) for i in range(n)]
    full = {}
    for bone, fn in tracks.items():
        pts = [fn(t) for t in times]
        full[bone] = {"x": [p[0] for p in pts], "y": [p[1] for p in pts],
                      "rotation": [0.0] * n, "scaleX": [1.0] * n, "scaleY": [1.0] * n}
    return {"times": times, "tracks": full, "events": []}


def test_motion_report_clean_circle():
    rep = analysis.motion_report(_sampled({
        "hand": lambda t: (100 * math.cos(2 * math.pi * t), 100 * math.sin(2 * math.pi * t)),
        "still": lambda t: (0.0, 0.0),
    }), loop=True)
    assert rep["issues"] == [] and (rep["moving_bones"], rep["static_bones"]) == (1, 1)
    assert rep["most_active"][0]["bone"] == "hand"
    assert rep["peak_speed"] == pytest.approx(2 * math.pi * 100, rel=0.01)


def test_motion_report_finds_loop_gap_pop_and_dead_hold():
    rep = analysis.motion_report(_sampled({
        "hand": lambda t: (200 * min(t, 0.5) + (60 if t > 0.25 else 0), 0.0),
    }), loop=True)
    by_code = {i["code"]: i for i in rep["issues"]}
    assert set(by_code) == {"loop_gap", "pop", "dead_hold"}
    assert "t=0.267" in by_code["pop"]["where"]
    assert by_code["dead_hold"]["where"] == "t=0.5 to t=1.0"
    # A physics-driven bone never ends where it starts on a single pass: ignored.
    rep = analysis.motion_report(_sampled({"hair": lambda t: (50 * t, 0.0)}), loop=True,
                                 physics_bones={"hair"})
    assert "loop_gap" not in {i["code"] for i in rep["issues"]}


def test_ground_contacts_speed_and_foot_slide():
    def planted(t):  # stance 0..0.6 sliding back at 100 units/s, then a lifted swing
        if t <= 0.6:
            return (30 - 100 * t, 0.0)
        u = (t - 0.6) / 0.4
        return (-30 + 60 * u, 20 * math.sin(math.pi * u))

    rep = analysis.motion_report(_sampled({"foot": planted}), loop=True, ground_bones=["foot"])
    assert rep["issues"] == [] and rep["ground_speed"] == pytest.approx(100, rel=0.02)
    assert rep["contacts"][0]["from"] == 0 and rep["contacts"][0]["to"] == pytest.approx(0.6, abs=0.02)

    def skating(t):  # same contact, but the foot eases instead of moving with the ground
        if t <= 0.6:
            return (30 - 60 * (1 - math.cos(math.pi * t / 0.6)) / 2, 0.0)
        return planted(t)

    rep = analysis.motion_report(_sampled({"foot": skating}), loop=True, ground_bones=["foot"])
    assert [i["code"] for i in rep["issues"]] == ["foot_slide"]
    with pytest.raises(ValueError, match="ground bone"):
        analysis.motion_report(_sampled({"foot": planted}), loop=True, ground_bones=["nope"])
