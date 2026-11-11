"""symbol_anticipation: the tremble must not beat against the game's frame rate.

A 14 Hz tremble sampled at 30 fps aliases to a 2 Hz envelope: every 0.5 s the
sampled rotation barely moves and the tremble seems to stop. A frequency of
display_fps / n (n >= 3) samples the same phases every cycle, so every frame moves.
"""

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
        "slots": [{"name": "gem", "bone": "symbol", "attachment": "gem"}],
        "skins": [{"name": "default", "attachments": {"gem": {"gem": {"width": 100, "height": 100}}}}],
        "animations": {},
    }


def _steps(symbol, fps, duration=1.0):
    keys = symbol["animations"]["anticipation"]["bones"]["symbol"]["rotate"]
    spec = fmt.BONE_TIMELINES["rotate"]
    n = round(fps * duration)
    vals = [an.sample(spec, keys, i / fps)[0] for i in range(n + 1)]
    return [abs(b - a) for a, b in zip(vals, vals[1:])]


def _weakest(symbol, fps):
    """Smallest motion over any 0.1 s window: the largest frame step inside
    the window, minimised over windows. A beating tremble collapses here."""
    st = _steps(symbol, fps)
    w = fps // 10
    return min(max(st[i:i + w]) for i in range(len(st) - w + 1))


def test_default_tremble_is_clean_at_30_fps(symbol):
    info = gen.symbol_anticipation(symbol)
    assert info["tremble_hz"] == pytest.approx(10.0)
    assert info["frames_per_tremble"] == 3
    assert "warnings" not in info


def test_14hz_snaps_to_a_divisor_of_30_fps(symbol):
    info = gen.symbol_anticipation(symbol, frequency=14)  # the former default
    assert info["tremble_hz"] == pytest.approx(10.0)
    assert info["display_fps"] == 30
    assert info["frames_per_tremble"] == 3
    assert any("14" in w and "10" in w for w in info.get("warnings", []))
    assert validate_data(symbol).ok


@pytest.mark.parametrize("fps,floor", [(30, 1.6), (60, 0.8)])
def test_snapped_tremble_never_fades(symbol, fps, floor):
    gen.symbol_anticipation(symbol, frequency=14, tremble=2.5, swell=0)
    # 10 Hz at 30 fps: steps 0.87 A, 1.73 A, 0.87 A in every 0.1 s window
    assert _weakest(symbol, fps) > floor * 2.5


def test_unsnapped_14hz_beats_at_30fps(symbol):
    """The old behaviour (display_fps=None) is kept on demand, and it beats."""
    info = gen.symbol_anticipation(symbol, frequency=14, tremble=2.5, swell=0, display_fps=None)
    assert info["tremble_hz"] == pytest.approx(14.0)
    assert "frames_per_tremble" not in info
    assert _weakest(symbol, 30) < 0.7 * 2.5  # 1.70 A once snapped to 10 Hz


def test_divisor_frequency_is_kept_without_warning(symbol):
    info = gen.symbol_anticipation(symbol, frequency=15, display_fps=60)
    assert info["tremble_hz"] == pytest.approx(15.0)
    assert info["frames_per_tremble"] == 4
    assert not info.get("warnings")


def test_never_two_frames_per_cycle(symbol):
    # 15 Hz at 30 fps = 2 frames per cycle: a phase-0 sine samples 0 then 0.
    info = gen.symbol_anticipation(symbol, frequency=15)
    assert info["frames_per_tremble"] >= 3
    assert info["tremble_hz"] == pytest.approx(10.0)


def test_duration_off_the_frame_grid_warns_and_keeps_a_seamless_loop(symbol):
    info = gen.symbol_anticipation(symbol, duration=0.95, frequency=14)
    assert any("frame" in w for w in info.get("warnings", []))
    anim = symbol["animations"]["anticipation"]
    for tl, keys in anim["bones"]["symbol"].items():
        spec = fmt.BONE_TIMELINES[tl]
        assert an.sample(spec, keys, 0) == pytest.approx(an.sample(spec, keys, 0.95), abs=1e-3)


def test_tool_accepts_display_fps(symbol, tmp_path):
    import json

    from spine2d_mcp.tools.animation import generate_animation

    p = tmp_path / "s.json"
    p.write_text(json.dumps(symbol))
    res = generate_animation(str(p), "symbol_anticipation", params={"display_fps": 60, "frequency": 12})
    assert res["details"]["tremble_hz"] == pytest.approx(12.0)
    assert res["details"]["frames_per_tremble"] == 5
