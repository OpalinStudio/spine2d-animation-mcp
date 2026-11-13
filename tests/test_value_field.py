"""Single-value timelines read only `value`: a key written with `y` (or any
other stray number) is ignored by the 4.3 reader, which then uses the
default (0) and the clip does not move. set_keyframes must catch it and the
validator must warn about it."""

import json

import pytest

from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import validator as va
from spine2d_mcp.tools import animation as ta
from spine2d_mcp.tools import skeleton as ts


@pytest.fixture
def sk(tmp_path):
    path = str(tmp_path / "s.json")
    ts.create_skeleton(path)
    ts.add_bone(path, "b", length=40)
    return path


@pytest.mark.parametrize(
    "timeline, field",
    [("translatey", "y"), ("translatex", "x"), ("scalex", "x"), ("scaley", "y"),
     ("shearx", "x"), ("sheary", "y")],
)
def test_axis_field_on_a_single_value_timeline_becomes_value(sk, timeline, field):
    res = ta.set_keyframes(sk, "a", "bone", "b", keys=[
        {"time": 0, field: 0}, {"time": 0.5, field: 12}], timeline=timeline)
    keys = json.load(open(sk))["animations"]["a"]["bones"]["b"][timeline]
    assert [k.get("value") for k in keys] == [0, 12]
    assert all(field not in k for k in keys)
    assert any(f"`{field}`" in w and "value" in w for w in res.get("warnings", []))


def test_stray_number_without_value_is_refused(sk):
    with pytest.raises(an.AnimationError, match="value"):
        ta.set_keyframes(sk, "a", "bone", "b", keys=[{"time": 0, "x": 5}],
                         timeline="rotate")
    with pytest.raises(an.AnimationError, match="value"):
        an.set_keys({}, "slot", "s", "alpha", [{"time": 0, "a": 0.5}])
    with pytest.raises(an.AnimationError, match="value"):
        an.set_keys({}, "physics", "p", "mix", [{"time": 0, "mix": 0.3}])


def test_both_axes_on_a_single_axis_timeline_are_refused(sk):
    with pytest.raises(an.AnimationError, match="translatey"):
        ta.set_keyframes(sk, "a", "bone", "b", keys=[{"time": 0, "x": 1, "y": 2}],
                         timeline="translatey")


def test_correct_keys_are_unchanged_and_silent(sk):
    res = ta.set_keyframes(sk, "a", "bone", "b", keys=[
        {"time": 0, "value": 0}, {"time": 0.5, "value": 12}], timeline="translatey")
    assert "warnings" not in res
    res = ta.set_keyframes(sk, "a", "bone", "b", keys=[
        {"time": 0, "x": 1, "y": 2}], timeline="translate")
    assert "warnings" not in res
    # IK keys keep their boolean fields.
    keys = an.set_keys({}, "ik", "ik1", None, [
        {"time": 0, "mix": 1, "bendPositive": False, "compress": True}])
    assert keys[0]["bendPositive"] is False


def test_validator_warns_on_fields_the_reader_ignores():
    data = {
        "skeleton": {"spine": "4.3.26"},
        "bones": [{"name": "root"}],
        "animations": {"a": {"bones": {"root": {
            "translatey": [{"time": 0, "value": 0}, {"time": 0.5, "y": 12}],
            "rotate": [{"time": 0, "value": 3}],
        }}}},
    }
    rep = va.validate_data(data)
    hits = [w for w in rep.warnings if "translatey" in w and "`y`" in w]
    assert len(hits) == 1, rep.warnings
    assert "value" in hits[0]
    assert not [w for w in rep.warnings if "rotate" in w]


def test_validator_accepts_ik_and_physics_fields():
    data = {
        "skeleton": {"spine": "4.3.26"},
        "bones": [{"name": "root"}, {"name": "a", "parent": "root", "length": 10},
                  {"name": "t", "parent": "root"}],
        "ik": [{"name": "ik1", "bones": ["a"], "target": "t"}],
        "animations": {"x": {"ik": {"ik1": [
            {"time": 0, "mix": 0.5, "softness": 2, "bendPositive": False,
             "compress": True, "stretch": True}]}}},
    }
    rep = va.validate_data(data)
    assert not [w for w in rep.warnings if "ignore" in w], rep.warnings
