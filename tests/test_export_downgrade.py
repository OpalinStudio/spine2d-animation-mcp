"""Export to an older data version (4.3 -> 4.2): the editor only says "may
lose information". The MCP sets the export `version` and lists the 4.3-only
features that disappear (https://esotericsoftware.com/forum/d/30848)."""

import json
import stat
import sys

import pytest

from spine2d_mcp.cli import spine_cli as cli
from spine2d_mcp.spine import downgrade


def _rig() -> dict:
    return {
        "skeleton": {"spine": "4.3.26"},
        "bones": [{"name": "root"}, {"name": "a", "parent": "root"}, {"name": "b", "parent": "a"}],
        "slots": [{"name": "s", "bone": "a"}, {"name": "t", "bone": "b"}],
        "constraints": [
            {"type": "slider", "name": "bend", "animation": "pose", "time": 1},
            {"type": "ik", "name": "arm", "bones": ["a", "b"], "target": "root", "scaleY": "volume"},
            {"type": "ik", "name": "arm2", "bones": ["a"], "target": "root", "scaleY": "uniform"},
            {"type": "transform", "name": "same", "bones": ["b"], "source": "a",
             "properties": {"x": {"to": {"x": {}}}, "rotate": {"to": {"rotate": {"scale": 1}}}}},
            {"type": "transform", "name": "gear", "bones": ["b"], "source": "a",
             "properties": {"rotate": {"to": {"x": {"scale": 0.3}}}}},
        ],
        "skins": [{"name": "default", "attachments": {
            "s": {"clip": {"type": "clipping", "inverse": True, "vertexCount": 3, "vertices": [0, 0, 1, 0, 0, 1]},
                  "m": {"type": "mesh"}},
            "t": {"lm": {"type": "linkedmesh", "source": "m", "slot": "s"},
                  "lm2": {"type": "linkedmesh", "source": "m2"}},
        }}],
        "animations": {
            "pose": {"bones": {"b": {"rotate": [{"value": 60}]}}},
            "idle": {"slider": {"bend": {"time": [{"value": 0.5}]}}, "drawOrderFolder": [{"slots": ["s"], "keys": []}]},
        },
    }


def test_losses_lists_every_43_only_feature():
    items = downgrade.losses(_rig(), "4.2")
    got = {(i["feature"], i["name"]) for i in items}
    assert got == {
        ("slider", "bend"),
        ("ik_volume", "arm"),
        ("transform_mapping", "gear"),
        ("inverse_clipping", "default/s/clip"),
        ("linked_mesh_other_slot", "default/t/lm"),
        ("slider_keys", "idle"),
        ("draw_order_folder_keys", "idle"),
    }
    assert downgrade.losses(_rig(), "4.3") == []
    assert any("slider (1): bend" in w for w in downgrade.summary(items, "4.2"))


def test_target_version_is_major_minor():
    with pytest.raises(ValueError, match="major.minor"):
        downgrade.parse_target("4.2.43")
    assert downgrade.parse_target("4.2") == (4, 2)


def test_validate_skeleton_reports_downgrade(tmp_path):
    from spine2d_mcp.tools.skeleton import validate_skeleton

    p = tmp_path / "rig.json"
    p.write_text(json.dumps(_rig()))
    res = validate_skeleton(str(p), target_version="4.2")
    assert res["target_version"] == "4.2"
    assert {i["feature"] for i in res["downgrade_losses"]} >= {"slider", "slider_keys"}
    assert "downgrade_losses" not in validate_skeleton(str(p))


@pytest.fixture
def fake_spine(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("fake exe is a shell script")
    exe = tmp_path / "Spine"
    seen = tmp_path / "settings.jsonl"
    # Records the settings file content, then writes a 4.2 "-from-" export
    # that still carries the slider in a top-level key (as 4.3.26 does).
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, os\n"
        "a = sys.argv[1:]\n"
        "e = a[a.index('-e') + 1]\n"
        f"open({str(seen)!r}, 'a').write(open(e).read().replace('\\n', ' ') + '\\n')\n"
        "o = a[a.index('-o') + 1]\n"
        "os.makedirs(o, exist_ok=True)\n"
        "json.dump({'skeleton': {'spine': '4.2-from-4.3.26'}, 'bones': [], 'slider': [{'name': 'bend'}]},"
        " open(os.path.join(o, 'rig.json'), 'w'))\n"
        "print('Exporting JSON from 4.3 to 4.2 may lose information.')\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SPINE_EXE", str(exe))
    monkeypatch.delenv("SPINE_VERSION", raising=False)
    return lambda: [json.loads(line) for line in seen.read_text().splitlines()]


def test_spine_export_target_version_sets_version_and_warns(fake_spine, tmp_path):
    from spine2d_mcp.tools.cli import spine_export

    src = tmp_path / "rig43.json"
    src.write_text(json.dumps(_rig()))
    res = spine_export(str(tmp_path / "rig.spine"), str(tmp_path / "out"), format="json",
                       target_version="4.2", audit_json=str(src))
    assert fake_spine()[-1]["version"] == "4.2"
    # 4.3.26 reads `version` only from class "export-json" (class "json" ignores it)
    assert fake_spine()[-1]["class"] == "export-json"
    assert res["target_version"] == "4.2"
    assert {i["feature"] for i in res["downgrade_losses"]} >= {"slider", "transform_mapping"}
    w = " | ".join(res["warnings"])
    assert "lossy downgrade" in w and "slider (1): bend" in w
    assert "rig.json (4.2-from-4.3.26): keys ['slider']" in w


def test_spine_export_target_version_guards(fake_spine, tmp_path):
    from spine2d_mcp.tools.cli import spine_export

    with pytest.raises(ValueError):
        spine_export("p.spine", str(tmp_path / "o"), format="json", target_version="4.2.43")
    with pytest.raises(ValueError):
        spine_export("p.spine", str(tmp_path / "o"), format="png", skeleton="x", target_version="4.2")
    with pytest.raises(ValueError, match="binary"):
        spine_export("p.spine", str(tmp_path / "o"), format="binary", target_version="4.2")
    res = spine_export("p.spine", str(tmp_path / "o"), format="json", target_version="4.2")
    assert fake_spine()[-1]["version"] == "4.2"
    assert any("no audit_json" in w for w in res["warnings"])
    # no target_version: settings unchanged, no new fields (backward compatible)
    res = spine_export("p.spine", str(tmp_path / "o2"), format="json")
    assert "version" not in fake_spine()[-1] and "target_version" not in res
    assert cli is not None


def test_output_check_flags_a_version_that_was_not_applied(tmp_path):
    from spine2d_mcp.tools.cli import _foreign_keys_in_output

    (tmp_path / "a.json").write_text(json.dumps({"skeleton": {"spine": "4.3.26"}, "constraints": []}))
    (tmp_path / "b.json").write_text(json.dumps({"skeleton": {"spine": "4.2-from-4.3.26"}, "bones": []}))
    w = _foreign_keys_in_output(str(tmp_path), "4.2")
    assert w == ["a.json: stamped '4.3.26', not 4.2: the version was not applied"]
