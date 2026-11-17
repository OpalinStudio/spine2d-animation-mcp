"""Overlays replay the real queue of a track, as the game sets it: `mix_out`
(addEmptyAnimation after a one-shot layer, back to the tracks below) and
`then` (addAnimation: the next clip starts when the previous one ends)."""

import pytest

from spine2d_mcp.runtime import fetch
from spine2d_mcp.runtime import render as rr
from spine2d_mcp.runtime import worker


@pytest.fixture(scope="module")
def runtime_ok():
    try:
        fetch.ensure_runtime()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            worker._launch(p).close()
    except Exception as e:  # no network on first run, no Chromium...
        pytest.skip(f"official runtime not available: {e}")


@pytest.fixture
def nodder(make_psd, tmp_path):
    """A head keyed at 0 (low), 40 (high, 1 s) and 20 (mid, 0.5 s)."""
    from spine2d_mcp.pipeline import import_psd_to_spine
    from spine2d_mcp.spine import animation as an
    from spine2d_mcp.spine import document as doc

    res = import_psd_to_spine(make_psd([("head", 160, 20, 80, 80), ("body", 150, 110, 100, 180)]),
                              str(tmp_path / "nodder"), export_images=True)
    data = doc.load(res.project_path)
    anims = data.setdefault("animations", {})
    for name, value, end in (("low", 0, 1), ("high", 40, 1), ("mid", 20, 0.5)):
        an.set_keys(anims.setdefault(name, {}), "bone", "head", "rotate",
                    [{"value": value}, {"time": end, "value": value}])
    doc.save(data, res.project_path)
    return str(res.project_path)


def _head(skeleton, overlays, times, duration=3):
    s = rr.sample(skeleton, "low", bones=["head"], times=times, loop=True, duration=duration,
                  overlays=overlays)
    rot = s["tracks"]["head"]["rotation"]
    return [r - rot[0] for r in rot]


def test_one_shot_layer_fades_back_with_mix_out(runtime_ok, nodder):
    layer = {"track": 1, "animation": "high", "start": 0.3}
    assert _head(nodder, [layer], [0.2, 1.2, 1.8]) == pytest.approx([0, 40, 40], abs=0.01)  # held
    _, fading, back = _head(nodder, [{**layer, "mix_out": 0.2}], [0.2, 1.2, 1.8])
    assert 5 < fading < 35 and back == pytest.approx(0, abs=0.01)


def test_then_queues_the_next_clip_when_the_first_ends(runtime_ok, nodder):
    # high (1 s) set at 0.3 on track 1, then mid: mid starts at 1.3, a cut (mix 0).
    layer = {"track": 1, "animation": "high", "start": 0.3, "then": [{"animation": "mid"}]}
    assert _head(nodder, [layer], [0.2, 1.2, 1.4, 1.75]) == pytest.approx([0, 40, 20, 20], abs=0.01)


def test_then_with_mix_ends_the_crossfade_at_the_end_of_the_previous_clip(runtime_ok, nodder):
    # mix 0.2, delay 0: the crossfade runs 1.1 -> 1.3, as AnimationState.addAnimation computes it.
    layer = {"track": 1, "animation": "high", "start": 0.3, "then": [{"animation": "mid", "mix": 0.2}]}
    _, before, mid, after = _head(nodder, [layer], [0.2, 1.05, 1.2, 1.35])
    assert before == pytest.approx(40, abs=0.01) and 22 < mid < 38 and after == pytest.approx(20, abs=0.01)


def test_then_and_mix_out_fade_back_after_the_last_queued_clip(runtime_ok, nodder):
    layer = {"track": 1, "animation": "high", "start": 0.3, "mix_out": 0.2,
             "then": [{"animation": "mid", "delay": 1.1}]}
    # delay > 0 counts from the START of the previous clip (Spine API): mid plays 1.4 -> 1.9
    # (high holds its last frame 1.3 -> 1.4), then the track fades back over 1.7 -> 1.9.
    got = _head(nodder, [layer], [0.2, 1.35, 1.5, 2.2])
    assert got == pytest.approx([0, 40, 20, 0], abs=0.01)


def test_bad_then_is_refused_before_rendering(nodder):
    with pytest.raises(rr.RuntimeRenderError, match="then"):
        rr.sample(nodder, "low", overlays=[{"animation": "high", "start": 0, "then": "mid"}])
    with pytest.raises(rr.RuntimeRenderError, match="animation"):
        rr.sample(nodder, "low", overlays=[{"animation": "high", "start": 0, "then": [{"delay": 1}]}])
