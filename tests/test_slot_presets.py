"""Slot-game symbol presets: valid data, clean loops, chainable rest poses."""

import pytest

from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import format as fmt
from spine2d_mcp.spine import generators as gen
from spine2d_mcp.spine.validator import validate_data


@pytest.fixture
def symbol():
    return {
        "skeleton": {"spine": "4.3.26", "images": "./images/"},
        "bones": [{"name": "root"}, {"name": "symbol", "parent": "root"}],
        "slots": [
            {"name": "glow", "bone": "symbol", "attachment": "glow", "blend": "additive"},
            {"name": "gem", "bone": "symbol", "attachment": "gem"},
        ],
        "skins": [{"name": "default", "attachments": {
            "glow": {"glow": {"width": 140, "height": 140}},
            "gem": {"gem": {"width": 100, "height": 100}},
        }}],
        "animations": {},
    }


def _bone_values(anim, bone, t):
    out = {}
    for tl, keys in anim.get("bones", {}).get(bone, {}).items():
        out[tl] = an.sample(fmt.BONE_TIMELINES[tl], keys, t)
    return out


REST = {"scale": [1, 1], "rotate": [0], "translatey": [0], "translate": [0, 0]}


def _at_rest(values):
    for tl, v in values.items():
        assert v == pytest.approx(REST[tl], abs=1e-3), (tl, v)


def test_symbol_bone_default_is_only_child_of_root(symbol):
    assert gen.symbol_bone(symbol) == "symbol"
    symbol["bones"].append({"name": "other", "parent": "root"})
    assert gen.symbol_bone(symbol) == "root"


@pytest.mark.parametrize("preset", ["symbol_idle", "symbol_land", "symbol_win", "symbol_anticipation"])
def test_symbol_presets_start_and_end_at_rest(symbol, preset):
    info = gen.SLOT_PRESETS[preset](symbol)
    assert validate_data(symbol).ok
    anim = symbol["animations"][info["animation"]]
    dur = an.animation_duration(anim)
    assert dur == pytest.approx(info["duration"], abs=1e-6)
    if preset != "symbol_land":  # land starts above the cell, by design
        _at_rest(_bone_values(anim, "symbol", 0))
    _at_rest(_bone_values(anim, "symbol", dur))


def test_symbol_win_pops_and_flashes(symbol):
    info = gen.symbol_win(symbol, pop=0.3, flash_slots=["gem"], glow_slots=["glow"])
    anim = symbol["animations"]["win"]
    sx, sy = an.sample(fmt.BONE_TIMELINES["scale"], anim["bones"]["symbol"]["scale"], info["pop_time"])
    assert sx == pytest.approx(1.3) and sy == pytest.approx(1.3)
    assert symbol["slots"][1]["dark"] == "000000"  # tint black enabled for the flash
    assert "rgba2" in anim["slots"]["gem"] and "alpha" in anim["slots"]["glow"]
    assert validate_data(symbol).ok


def test_symbol_land_squashes_on_impact(symbol):
    info = gen.symbol_land(symbol, drop=50, squash=0.2)
    anim = symbol["animations"]["land"]
    assert an.sample(fmt.BONE_TIMELINES["translatey"], anim["bones"]["symbol"]["translatey"], 0) == [50]
    sx, sy = an.sample(fmt.BONE_TIMELINES["scale"], anim["bones"]["symbol"]["scale"], info["impact_time"])
    assert sx == pytest.approx(1.2) and sy == pytest.approx(0.8)


def test_symbol_anticipation_loops_seamlessly(symbol):
    gen.symbol_anticipation(symbol, duration=1.0, frequency=13.6)
    anim = symbol["animations"]["anticipation"]
    for tl, keys in anim["bones"]["symbol"].items():
        spec = fmt.BONE_TIMELINES[tl]
        assert an.sample(spec, keys, 0) == pytest.approx(an.sample(spec, keys, 1.0), abs=1e-3)


def test_symbol_dim_darkens_every_slot(symbol):
    gen.symbol_dim(symbol, amount=0.5, alpha=0.8)
    anim = symbol["animations"]["dim"]
    assert set(anim["slots"]) == {"glow", "gem"}
    end = anim["slots"]["gem"]["rgba"][-1]["color"]
    assert end.lower() == "808080cc"
    assert validate_data(symbol).ok


def test_generate_animation_tool_dispatches_slot_presets(symbol, tmp_path):
    import json

    from spine2d_mcp.tools.animation import generate_animation

    p = tmp_path / "symbol.json"
    p.write_text(json.dumps(symbol))
    res = generate_animation(str(p), "symbol_win", params={"pop": 0.25})
    assert res["animation"] == "win" and res["duration"] == pytest.approx(1.2)
    assert "win" in json.loads(p.read_text())["animations"]


def test_dark_slot_color_timelines_become_two_color(symbol, tmp_path):
    """Spine 4.3.26 editor import crashes on curved rgba/rgb keys of a tint
    black slot: save() rewrites them as rgba2/rgb2 with the dark color held."""
    from spine2d_mcp.spine import document as doc

    gen.symbol_win(symbol, flash_slots=["gem"])  # gives gem a dark color
    gen.symbol_dim(symbol, amount=0.5)
    report = doc.save(symbol, tmp_path / "s.json")
    gem = symbol["animations"]["dim"]["slots"]["gem"]
    assert "rgba" not in gem and len(gem["rgba2"]) == 2
    k0 = gem["rgba2"][0]
    assert k0["light"] == "ffffffff" and k0["dark"] == "000000" and len(k0["curve"]) == 28
    assert gem["rgba2"][1]["light"].lower() == "808080ff"
    assert "rgba" in symbol["animations"]["dim"]["slots"]["glow"]  # no dark color: untouched
    assert any("dim/gem/rgba" in w for w in report.warnings)
    assert validate_data(symbol).ok


@pytest.fixture
def tile():
    """Reel-cell symbol: background + clipping on the container, the
    character on its own bone (synthetic, like a real tile rig)."""
    return {
        "skeleton": {"spine": "4.3.26", "images": "./images/"},
        "bones": [
            {"name": "root"}, {"name": "cell", "parent": "root"},
            {"name": "center", "parent": "cell"},
            {"name": "bg", "parent": "center"},
            {"name": "prop", "parent": "center"},
            {"name": "body", "parent": "center"},
            {"name": "head", "parent": "body"},
        ],
        "slots": [
            {"name": "bg", "bone": "bg", "attachment": "bg"},
            {"name": "cell_mask", "bone": "center", "attachment": "cell_mask"},
            {"name": "prop", "bone": "prop", "attachment": "prop"},
            {"name": "body", "bone": "body", "attachment": "body"},
            {"name": "head", "bone": "head", "attachment": "head"},
        ],
        "skins": [{"name": "default", "attachments": {
            "bg": {"bg": {"width": 200, "height": 200}},
            "cell_mask": {"cell_mask": {"type": "clipping", "end": "head",
                                        "vertexCount": 4,
                                        "vertices": [-90, -90, 90, -90, 90, 90, -90, 90]}},
            "prop": {"prop": {"width": 30, "height": 40}},
            "body": {"body": {"width": 100, "height": 80}},
            "head": {"head": {"width": 60, "height": 60}},
        }}],
        "animations": {},
    }


def test_tile_slots_detects_background_and_cell_mask(tile):
    assert set(gen.tile_slots(tile)) == {"bg", "cell_mask"}


def test_tile_slots_ignore_non_leading_words_and_shine_masks(tile):
    tile["slots"] += [
        {"name": "label_case_01", "bone": "body"},
        {"name": "shine_mask", "bone": "head"},
    ]
    tile["skins"][0]["attachments"]["shine_mask"] = {"shine_mask": {
        "type": "clipping", "vertexCount": 3, "vertices": [0, 0, 10, 0, 0, 10]}}
    assert set(gen.tile_slots(tile)) == {"bg", "cell_mask"}
    assert gen.symbol_bone(tile) == "body"


def test_symbol_bone_skips_the_tile_container(tile):
    # The container (center) carries the background and the clipping mask:
    # animating it would move the frame out of its reel cell.
    assert gen.symbol_bone(tile) == "body"


@pytest.mark.parametrize("preset", ["symbol_idle", "symbol_land", "symbol_win", "symbol_anticipation"])
def test_symbol_presets_on_tile_keep_the_frame_still(tile, preset):
    info = gen.SLOT_PRESETS[preset](tile)
    assert info["bone"] == "body"
    assert "warnings" not in info
    keyed = set(tile["animations"][info["animation"]]["bones"])
    assert keyed == {"body"}


def test_explicit_container_bone_warns_about_tile_slots(tile):
    info = gen.symbol_win(tile, bone="center")
    assert info["bone"] == "center"
    assert any("bg" in w and "cell_mask" in w for w in info["warnings"])


def test_symbol_bone_keeps_container_when_two_characters_compete(tile):
    tile["bones"].append({"name": "twin", "parent": "center"})
    tile["slots"] += [{"name": "twin_body", "bone": "twin"}, {"name": "twin_head", "bone": "twin"}]
    assert gen.symbol_bone(tile) == "center"
    info = gen.symbol_idle(tile)
    assert info["bone"] == "center" and info["warnings"]
