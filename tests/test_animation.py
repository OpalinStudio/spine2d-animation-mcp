"""Keys, curves, sampling, draw order, events, retime."""

import math

import pytest

from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import curves
from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine import format as fmt
from spine2d_mcp.spine import generators as gen
from spine2d_mcp.spine.validator import validate_data


def _skel():
    d = doc.new_skeleton()
    doc.add_bone(d, "arm", length=50)
    doc.add_slot(d, "a", "arm")
    doc.add_slot(d, "b", "arm")
    doc.add_slot(d, "c", "arm")
    return d


def test_preset_curve_becomes_absolute_bezier():
    anim = {}
    keys = an.set_keys(anim, "bone", "arm", "rotate", [
        {"time": 0, "value": 0, "curve": "easeInOut"},
        {"time": 2, "value": 90},
    ])
    assert keys[0]["curve"] == [0.84, 0, 1.16, 90]
    assert "curve" not in keys[1]
    assert "time" not in keys[0]  # time 0 omitted like Spine exports


def test_two_value_timeline_curve_has_eight_numbers():
    anim = {}
    keys = an.set_keys(anim, "bone", "arm", "translate", [
        {"time": 0, "x": 0, "y": 0, "curve": [0.25, 0.1, 0.25, 1]},
        {"time": 1, "x": 100, "y": -50},
    ])
    assert len(keys[0]["curve"]) == 8
    assert keys[0]["curve"][4:] == [0.25, -5, 0.25, -50]


def test_color_timeline_curve_per_channel():
    anim = {}
    keys = an.set_keys(anim, "slot", "a", "rgba", [
        {"time": 0, "color": "ffffffff", "curve": "easeIn"},
        {"time": 1, "color": "#ff000080"},
    ])
    assert len(keys[0]["curve"]) == 16
    assert keys[1]["color"] == "ff000080"


def test_sampling_matches_runtime_semantics():
    spec = fmt.BONE_TIMELINES["rotate"]
    keys = [{"value": 0, "curve": "stepped"}, {"time": 1, "value": 10}, {"time": 2, "value": 30}]
    assert an.sample(spec, keys, 0.5) == [0]
    assert an.sample(spec, keys, 1.5) == [20]
    assert an.sample(spec, keys, 5) == [30]
    assert an.sample(spec, [{"time": 1, "value": 3}], 0.5) is None  # before first key


def test_bezier_sampling_is_monotonic_and_hits_ends():
    spec = fmt.BONE_TIMELINES["rotate"]
    anim = {}
    keys = an.set_keys(anim, "bone", "arm", "rotate", [
        {"time": 0, "value": 0, "curve": "easeInOutCubic"}, {"time": 1, "value": 100}])
    vals = [an.sample(spec, keys, t / 20)[0] for t in range(21)]
    assert vals[0] == pytest.approx(0) and vals[-1] == pytest.approx(100)
    assert all(b >= a - 1e-6 for a, b in zip(vals, vals[1:]))
    assert vals[2] < 2  # slow start


def test_merge_inserting_a_key_rescales_existing_curve():
    anim = {}
    an.set_keys(anim, "bone", "arm", "rotate", [
        {"time": 0, "value": 0, "curve": "easeInOut"}, {"time": 2, "value": 100}])
    keys = an.set_keys(anim, "bone", "arm", "rotate", [{"time": 1, "value": 40}])
    assert [k.get("time", 0) for k in keys] == [0, 1, 2]
    c = keys[0]["curve"]
    assert 0 < c[0] < 1 and 0 < c[2] < 1  # control points stay inside the new segment
    assert c[3] == pytest.approx(40)


def test_inputs_are_validated():
    with pytest.raises(an.AnimationError):
        an.set_keys({}, "bone", "arm", "rotatez", [{"value": 1}])
    with pytest.raises(an.AnimationError):
        an.set_keys({}, "slot", "a", "rgba", [{"color": "fff"}])
    with pytest.raises(ValueError):
        an.set_keys({}, "bone", "arm", "rotate", [{"value": 1, "curve": "bouncy"}, {"time": 1}])


def test_all_timeline_kinds_validate():
    d = _skel()
    doc.add_bone(d, "t")
    doc.add_constraint(d, {"type": "ik", "name": "ik", "bones": ["arm"], "target": "t"})
    doc.add_constraint(d, {"type": "transform", "name": "tr", "source": "t", "bones": ["arm"],
                           "properties": {"x": {"to": {"x": {}}}}})
    doc.add_constraint(d, {"type": "physics", "name": "ph", "bone": "arm", "rotate": 1})
    d["animations"]["pose"] = {}
    doc.add_constraint(d, {"type": "slider", "name": "sl", "animation": "pose"})
    from spine2d_mcp.spine import attachments as att

    doc.set_attachment(d, "a", "m", att.grid_mesh(10, 10, 1, 1))
    doc.set_attachment(d, "b", "r", att.region(10, 10, sequence_count=4))
    anim = d["animations"].setdefault("all", {})
    an.set_keys(anim, "bone", "arm", "inherit", [{"inherit": "noScale"}])
    an.set_keys(anim, "bone", "arm", "shear", [{"x": 1, "y": 2, "curve": "ease"}, {"time": 1}])
    an.set_keys(anim, "slot", "a", "attachment", [{"name": "m"}, {"time": 1, "name": None}])
    an.set_keys(anim, "slot", "a", "rgba2", [{"light": "ffffffff", "dark": "000000", "curve": "easeOut"},
                                             {"time": 1, "light": "ff0000ff", "dark": "ffffff"}])
    an.set_keys(anim, "ik", "ik", None, [{"mix": 1, "curve": "easeIn"}, {"time": 1, "mix": 0, "bendPositive": False}])
    an.set_keys(anim, "transform", "tr", None, [{"mixX": 1, "curve": "easeIn"}, {"time": 1, "mixX": 0}])
    an.set_keys(anim, "physics", "", "wind", [{"value": 0, "curve": "easeIn"}, {"time": 1, "value": 5}])
    an.set_keys(anim, "physics", "ph", "reset", [{"time": 0.5}])
    an.set_keys(anim, "slider", "sl", "time", [{"value": 0, "curve": "easeIn"}, {"time": 1, "value": 1}])
    an.set_keys(anim, "deform", "a/m", None, [{"vertices": [0, 0, 5, 5], "curve": "easeInOut"}, {"time": 1}])
    an.set_keys(anim, "sequence", "default/b/r", None, [{"mode": "loop", "delay": 0.1}])
    an.set_event_keys(anim, [{"time": 0.3, "name": "step"}])
    doc.set_event(d, "step", int=1)
    an.set_draw_order_keys(anim, doc.slot_names(d), [{"time": 0.2, "order": ["c", "b", "a"]}, {"time": 0.8, "order": None}])
    an.set_draw_order_folder_keys(anim, ["b", "c"], [{"time": 0.4, "order": ["c", "b"]}])
    report = validate_data(d)
    assert report.ok, report.errors
    assert an.animation_duration(anim) == 1


def test_partial_draw_order():
    anim = {}
    keys = an.set_draw_order_keys(anim, ["a", "b", "c", "d"], [{"time": 0, "order": ["d", "a"]}])
    assert doc.decode_draw_order(keys[0], ["a", "b", "c", "d"]) == ["d", "b", "c", "a"]


def test_retime_scales_times_and_curves():
    anim = {}
    an.set_keys(anim, "bone", "arm", "rotate", [{"time": 0, "value": 0, "curve": "easeIn"}, {"time": 2, "value": 9}])
    an.retime(anim, 0.5)
    keys = anim["bones"]["arm"]["rotate"]
    assert keys[1]["time"] == 1
    assert keys[0]["curve"][0] == pytest.approx(0.42)


def test_oscillate_reproduces_a_sine_and_loops():
    d = _skel()
    gen.oscillate(d, "osc", "arm", "rotate", amplitude=10, period=1, duration=2, phase=30)
    keys = d["animations"]["osc"]["bones"]["arm"]["rotate"]
    spec = fmt.BONE_TIMELINES["rotate"]
    for i in range(41):
        t = i / 20
        expected = 10 * math.sin(2 * math.pi * t + math.radians(30))
        assert an.sample(spec, keys, t)[0] == pytest.approx(expected, abs=0.3)  # cubic vs sine: <3% of amplitude
    assert keys[0]["value"] == pytest.approx(keys[-1]["value"])


def test_curve_presets_listed():
    assert "easeOutBack" in curves.preset_names()
