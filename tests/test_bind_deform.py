"""bind_mesh_weights on a mesh that already has deform keys: the keys must be
converted to the weighted layout (one offset per bone influence, in that
bone's space) so the setup pose looks the same, like the editor does."""

from __future__ import annotations

import json

from spine2d_mcp.spine.pose import Pose
from spine2d_mcp.tools import animation as ta
from spine2d_mcp.tools import skeleton as ts


def _rig(tmp_path):
    j = str(tmp_path / "s.json")
    ts.create_skeleton(j, overwrite=True)
    ts.add_bone(j, "a", parent="root", x=10, y=5, rotation=20, length=100, scale_x=1.2)
    ts.add_bone(j, "b", parent="a", x=100, rotation=-55, length=100, scale_y=0.8)
    ts.add_slot(j, "s", bone="a")
    ts.add_mesh_attachment(j, "s", "m", mode="grid", width=200, height=40, x=100,
                           cols=2, rows=1, color="ff0000ff")
    return j


def _mesh(j):
    d = json.load(open(j))
    return d, d["skins"][0]["attachments"]["s"]["m"]


def _full(key, n):
    out = [0.0] * int(key.get("offset", 0)) + [float(v) for v in key.get("vertices") or []]
    return out + [0.0] * (n - len(out))


def _world_unweighted(d, m, offsets):
    sb = Pose(d).bones["a"]
    v = m["vertices"]
    return [sb.local_to_world(v[i] + offsets[i], v[i + 1] + offsets[i + 1]) for i in range(0, len(v), 2)]


def _world_weighted(d, m, offsets):
    pose = Pose(d)
    names = [b["name"] for b in d["bones"]]
    v, out, i, f = m["vertices"], [], 0, 0
    while i < len(v):
        n = int(v[i]); i += 1
        wx = wy = 0.0
        for _ in range(n):
            bone = pose.bones[names[int(v[i])]]
            x, y = bone.local_to_world(v[i + 1] + offsets[f], v[i + 2] + offsets[f + 1])
            wx += x * v[i + 3]; wy += y * v[i + 3]
            i += 4; f += 2
        out.append((wx, wy))
    return out


def test_bind_converts_existing_deform_keys(tmp_path):
    j = _rig(tmp_path)
    d, m = _mesh(j)
    n = len(m["vertices"])
    full = [3.0 * (i % 5) - 4.0 for i in range(n)]
    sparse = [0.0] * 4 + [7.0, -2.0, 0.0, 5.0]  # written with an offset
    ta.set_keyframes(j, "anim", "deform", "s/m", keys=[
        {"time": 0},
        {"time": 0.5, "vertices": full},
        {"time": 1, "offset": 4, "vertices": sparse[4:]},
    ], timeline="deform")
    d0, m0 = _mesh(j)
    want = [_world_unweighted(d0, m0, _full(k, n))
            for k in d0["animations"]["anim"]["attachments"]["default"]["s"]["m"]["deform"]]

    res = ts.bind_mesh_weights(j, "s", "m", ["a", "b"])
    assert res.get("deform_converted") == 3
    d1, m1 = _mesh(j)
    v, i, infl = m1["vertices"], 0, 0
    while i < len(v):
        infl += int(v[i]); i += 1 + 4 * int(v[i])
    keys = d1["animations"]["anim"]["attachments"]["default"]["s"]["m"]["deform"]
    assert len(keys) == 3
    assert "vertices" not in keys[0] or not any(keys[0]["vertices"])
    for k, w in zip(keys, want):
        assert len(k.get("vertices") or []) + int(k.get("offset", 0)) <= 2 * infl
        got = _world_weighted(d1, m1, _full(k, 2 * infl))
        for (gx, gy), (wx, wy) in zip(got, w):
            assert abs(gx - wx) < 0.02 and abs(gy - wy) < 0.02
    # The moving key is now as long as the weighted layout needs.
    assert len(keys[1]["vertices"]) + int(keys[1].get("offset", 0)) > n
    assert ts.validate_skeleton(j)["ok"]


def test_bind_without_deform_reports_zero(tmp_path):
    j = _rig(tmp_path)
    res = ts.bind_mesh_weights(j, "s", "m", ["a", "b"])
    assert res.get("deform_converted") == 0
    assert not any("deform" in w for w in res.get("warnings", []))
