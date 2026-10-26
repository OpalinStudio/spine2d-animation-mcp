"""End-to-end through the MCP tool layer: build a rig from scratch, rig it
with 4.3 features, animate, preview, and round-trip through FastMCP."""

import asyncio
import json

from PIL import Image

from spine2d_mcp.spine import document as doc
from spine2d_mcp.spine.validator import validate_data
from spine2d_mcp.tools import animation as ta
from spine2d_mcp.tools import assets, mcp
from spine2d_mcp.tools import skeleton as ts


def _images(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name, size, color in (("body", (60, 120), "#3b82f6"), ("head", (70, 70), "#f97316"),
                              ("tail", (30, 120), "#22c55e"), ("eye", (12, 12), "#ffffff")):
        Image.new("RGBA", size, color).save(folder / f"{name}.png")


def test_full_rig_workflow(tmp_path):
    sk = str(tmp_path / "creature.json")
    _images(tmp_path / "images")
    ts.create_skeleton(sk, 300, 400)
    ts.add_bone(sk, "hip", y=120)
    ts.add_bone(sk, "body", "hip", rotation=90, length=120)
    ts.add_bone(sk, "head", "body", x=120, rotation=-90, length=60)
    ts.add_bone(sk, "tail1", "hip", rotation=180, length=40, color="22c55eff")
    ts.add_bone(sk, "tail2", "tail1", x=40, length=40)
    ts.add_bone(sk, "tail3", "tail2", x=40, length=40)
    ts.add_bone(sk, "face-ctrl", "head", x=30, y=0, icon="circle")
    ts.add_slot(sk, "tail", "tail1", attachment="tail")
    ts.add_slot(sk, "body", "body", attachment="body")
    ts.add_slot(sk, "head", "head", attachment="head")
    ts.add_slot(sk, "eye", "head", attachment="eye")
    ts.add_region_attachment(sk, "body", "body", 60, 120, x=60, rotation=-90)
    ts.add_region_attachment(sk, "head", "head", 70, 70, y=30)
    ts.add_region_attachment(sk, "eye", "eye", 12, 12, x=15, y=40)
    r = ts.add_mesh_attachment(sk, "tail", "tail", mode="grid", width=120, height=30, cols=3, rows=1,
                               x=60, weight_bones=["tail1", "tail2", "tail3"])
    assert r["weighted"] and r["vertex_count"] == 8
    ts.add_clipping_attachment(sk, "body", "clip", [[0, -40], [120, -40], [120, 40], [0, 40]],
                               end_slot="head", inverse=True, convex=True)
    ts.update_slot(sk, "body", attachment="body")
    ts.add_ik_constraint(sk, ["tail2", "tail3"], create_target=True, scale_y="volume", stretch=True)
    ts.add_physics_constraint(sk, ["tail1", "tail2"], rotate=1, gravity=20)
    ta.manage_animation(sk, "create", "smile-pose", color="ff00ffff")
    ta.set_keyframes(sk, "smile-pose", "bone", "head", [{"value": 0}, {"time": 1, "value": 15}],
                     timeline="rotate")
    ts.add_slider(sk, "smile", "smile-pose", bone="face-ctrl", property="y", scale=0.05)
    ts.add_transform_constraint(sk, "ctrl-scale", "face-ctrl", ["head"],
                                properties={"x": {"to": {"scaleX": {"scale": 0.01}}}}, clamp=True)
    ts.add_skin(sk, "angry", bones=["face-ctrl"])
    ts.set_event(sk, "roar", string_value="ROAR", audio="roar.wav", volume=0.8)

    ta.generate_animation(sk, "idle", params={"roles": {"torso": "body"}})
    ta.generate_animation(sk, "follow_through", "wag", params={"bones": ["tail1", "tail2", "tail3"], "delay": 45})
    ta.generate_animation(sk, "flash", "hit", params={"slots": ["head", "body"]})
    ta.generate_animation(sk, "shake", "hit", params={"bone": "root"}, mode="merge")
    ta.set_keyframes(sk, "hit", "slot", "eye", [{"name": None}, {"time": 0.2, "name": "eye"}], timeline="attachment")
    ta.set_draw_order_keys(sk, "hit", [{"time": 0.1, "order": ["head", "body"]}, {"time": 0.3, "order": None}])
    ta.set_draw_order_keys(sk, "hit", [{"time": 0.1, "order": ["eye", "head"]}], folder_slots=["head", "eye"])
    ta.add_event_keys(sk, "hit", [{"time": 0.05, "name": "roar"}, {"time": 0.2, "name": "thud", "int": 2}])
    ta.set_keyframes(sk, "wag", "physics", "*", [{"value": 0, "curve": "easeIn"}, {"time": 1, "value": 30}],
                     timeline="wind")
    ta.set_keyframes(sk, "wag", "slider", "smile", [{"value": 0}, {"time": 1, "value": 1}], timeline="mix")
    ta.set_keyframes(sk, "wag", "deform", "tail/tail", [{"vertices": [5, 0] * 4, "curve": "easeInOut"}, {"time": 1}])
    ta.retime_animation(sk, "wag", target_duration=2)

    data = doc.load(sk)
    report = validate_data(data)
    assert report.ok, report.errors
    assert [c["type"] for c in data["constraints"]] == ["ik", "physics", "physics", "slider", "transform"]
    assert data["animations"]["smile-pose"]["color"] == "ff00ffff"
    assert data["events"]["thud"] == {}

    summary = ts.inspect_skeleton(sk)
    assert {a["name"] for a in summary["animations"]} == {"smile-pose", "idle", "wag", "hit"}

    frame = ta.render_preview(sk, str(tmp_path / "f.png"), animation="wag", time=0.5, show_bones=True)
    assert frame["missing_images"] == []
    sheet = ta.render_preview(sk, str(tmp_path / "s.png"), animation="idle", mode="sheet", frames=4, columns=2)
    gif = ta.render_preview(sk, str(tmp_path / "g.gif"), animation="hit", mode="gif", fps=10, width=128, height=128)
    for p in (frame, sheet, gif):
        assert Image.open(p["image"]).size[0] > 0

    # Renames keep everything consistent.
    ts.update_bone(sk, "tail3", new_name="tail-tip")
    ts.update_slot(sk, "head", new_name="face")
    ta.manage_animation(sk, "rename", "smile-pose", new_name="smile")
    data = doc.load(sk)
    assert validate_data(data).ok
    assert next(c for c in data["constraints"] if c["type"] == "slider")["animation"] == "smile"


def test_tools_reject_bad_edits_without_touching_file(tmp_path):
    sk = str(tmp_path / "s.json")
    ts.create_skeleton(sk)
    before = (tmp_path / "s.json").read_text()
    try:
        ts.add_slot(sk, "x", "ghost")
    except Exception as e:
        assert "ghost" in str(e)
    assert (tmp_path / "s.json").read_text() == before


def test_fastmcp_roundtrip(tmp_path):
    sk = str(tmp_path / "r.json")

    async def go():
        await mcp.call_tool("create_skeleton", {"skeleton": sk})
        await mcp.call_tool("add_bone", {"skeleton": sk, "name": "arm", "length": 40})
        await mcp.call_tool("generate_animation", {"skeleton": sk, "preset": "oscillate", "animation": "swing",
                                                   "params": {"bone": "arm", "amplitude": 20}})
        res = await mcp.call_tool("inspect_skeleton", {"skeleton": sk})
        tools = await mcp.list_tools()
        return res, tools

    res, tools = asyncio.run(go())
    text = res[0][0].text if isinstance(res, tuple) else res[0].text
    assert json.loads(text)["animations"][0]["name"] == "swing"
    names = {t.name for t in tools}
    assert {"spine_export", "add_slider", "set_keyframes", "render_preview", "import_psd_to_spine"} <= names
    assert len(names) >= 50


def test_atlas_pack_read_unpack(tmp_path):
    _images(tmp_path / "img")
    out = assets.pack_atlas(str(tmp_path / "img"), str(tmp_path / "atlas"), "creature")
    info = assets.read_atlas(out["atlas"])
    assert {r["name"] for r in info["regions"]} == {"body", "head", "tail", "eye"}
    un = assets.unpack_atlas_images(out["atlas"], str(tmp_path / "un"))
    assert un["images"] == 4
    assert Image.open(tmp_path / "un" / "head.png").size == (70, 70)
