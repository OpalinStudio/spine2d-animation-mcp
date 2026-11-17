"""no_overlap must follow every branch of a keyed tree: a torso that carries
two arms keyed on the same frames is two rigid chains, not zero."""

from spine2d_mcp.spine import analysis
from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import document as doc

KEYS = [{"value": 0, "curve": "easeInOut"}, {"time": 0.5, "value": 20, "curve": "easeInOut"},
        {"time": 1, "value": 0}]


def _rig():
    data = doc.new_skeleton()
    doc.add_bone(data, "torso", y=100, length=60)
    for side in ("l", "r"):
        doc.add_bone(data, f"upper_{side}", "torso", x=60, length=40)
        doc.add_bone(data, f"lower_{side}", f"upper_{side}", x=40, length=30)
    doc.add_bone(data, "neck", "torso", x=60, length=10)
    return data


def _key(data, anim, bone, keys=KEYS):
    an.set_keys(doc.animations(data).setdefault(anim, {}), "bone", bone, "rotate",
               [dict(k) for k in keys])


def _no_overlap(data, anim):
    return [i for i in analysis.analyze(data, anim)["issues"] if i["code"] == "no_overlap"]


def test_torso_with_two_arms_on_the_same_frames_gives_one_issue_per_arm():
    data = _rig()
    for b in ("torso", "upper_l", "lower_l", "upper_r", "lower_r"):
        _key(data, "cheer", b)
    issues = _no_overlap(data, "cheer")
    assert sorted(i["where"] for i in issues) == [
        "torso > upper_l > lower_l", "torso > upper_r > lower_r"]
    # the shared torso must not be offset twice: the fix staggers each arm only
    fixes = " ".join(i["fix"] for i in issues)
    assert "['upper_l', 'lower_l']" in fixes and "['upper_r', 'lower_r']" in fixes
    assert "torso" in issues[0]["fix"]


def test_arm_offset_from_the_torso_still_flags_the_rigid_arm_below():
    data = _rig()
    doc.add_bone(data, "hand_l", "lower_l", x=30, length=10)
    late = [dict(k, time=k.get("time", 0) + 0.1) for k in KEYS[:-1]] + [{"time": 1, "value": 0}]
    _key(data, "wave", "torso", late)
    for b in ("upper_l", "lower_l", "hand_l"):
        _key(data, "wave", b)
    issues = _no_overlap(data, "wave")
    assert [i["where"] for i in issues] == ["upper_l > lower_l > hand_l"]


def test_branches_with_overlap_stay_quiet():
    data = _rig()
    _key(data, "cheer", "torso")
    spec = an.spec_for("bone", "rotate")
    for side in ("l", "r"):
        for n, b in enumerate((f"upper_{side}", f"lower_{side}"), 1):
            _key(data, "cheer", b, an.shift_keys([dict(k) for k in KEYS], spec, 0.05 * n, 1.0))
    assert _no_overlap(data, "cheer") == []


def test_single_chain_report_is_unchanged():
    data = _rig()
    for b in ("torso", "upper_l", "lower_l"):
        _key(data, "swing", b)
    issues = _no_overlap(data, "swing")
    assert [i["where"] for i in issues] == ["torso > upper_l > lower_l"]
    assert "offset_keys(bones=['torso', 'upper_l', 'lower_l'], offset=0" in issues[0]["fix"]
