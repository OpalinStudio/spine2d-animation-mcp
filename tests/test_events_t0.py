"""Events keyed at t=0 must be reported by runtime_sample / runtime_render.

The page builds the instance with a zero step (the t=0 event fires there),
then used to clear every event before the capture, with or without warm-up.
"""

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
def beat(make_psd, tmp_path):
    """Two-part rig with a looping 1 s clip: `start` at 0, `step` at 0.5."""
    from spine2d_mcp.pipeline import import_psd_to_spine
    from spine2d_mcp.spine import animation as an
    from spine2d_mcp.spine import document as doc

    res = import_psd_to_spine(make_psd([
        ("head", 160, 20, 80, 80), ("body", 150, 110, 100, 180),
    ]), str(tmp_path / "beat"), export_images=True)
    data = doc.load(res.project_path)
    doc.set_event(data, "start")
    doc.set_event(data, "step")
    anim = data.setdefault("animations", {}).setdefault("beat", {})
    an.set_keys(anim, "bone", "head", "rotate", [{"value": 0}, {"time": 0.5, "value": 10}, {"time": 1, "value": 0}])
    an.set_event_keys(anim, [{"time": 0, "name": "start"}, {"time": 0.5, "name": "step"}])
    doc.save(data, res.project_path)
    return str(res.project_path)


def _names_times(events):
    return [(e["name"], e["time"]) for e in events]


@pytest.mark.parametrize("warmup", [0, 1, 2])
def test_sample_reports_the_event_at_zero(runtime_ok, beat, warmup):
    s = rr.sample(beat, "beat", bones=["head"], fps=30, warmup=warmup)
    assert _names_times(s["events"])[:2] == [("start", 0), ("step", 0.5)]
    # the capture covers [0, 1] inclusive: the next loop starts on the last frame
    assert [n for n, _ in _names_times(s["events"])].count("start") <= 2
    assert all(set(e) == {"time", "name", "track", "animation"} for e in s["events"])


def test_sample_exclusive_end_reports_start_once(runtime_ok, beat):
    s = rr.sample(beat, "beat", bones=["head"], times=[0, 0.25, 0.5, 0.75], warmup=1)
    assert _names_times(s["events"]) == [("start", 0), ("step", 0.5)]


@pytest.mark.parametrize("warmup", [0, 1])
def test_render_reports_the_event_at_zero(runtime_ok, beat, tmp_path, warmup):
    res = rr.render(beat, str(tmp_path / "f.gif"), format="gif", animation="beat", fps=10,
                    width=120, warmup=warmup)
    assert _names_times(res["events"])[:2] == [("start", 0), ("step", 0.5)]
