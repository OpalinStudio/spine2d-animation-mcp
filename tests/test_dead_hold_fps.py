"""dead_hold must not depend on the sampling rate: the same motion sampled at
30, 60 or 120 fps gives the same verdict (the threshold is a speed, not a
per-frame step)."""
import pytest

from spine2d_mcp.spine import analysis


def _sampled(drift, n):
    # 0 -> 200 units in 0.5 s, then a slow drift of `drift` units/s until 1 s.
    times = [i / (n - 1) for i in range(n)]
    xs = [400 * t if t <= 0.5 else 200 + drift * (t - 0.5) for t in times]
    return {"times": times, "events": [],
            "tracks": {"hand": {"x": xs, "y": [0.0] * n, "rotation": [0.0] * n,
                                "scaleX": [1.0] * n, "scaleY": [1.0] * n}}}


def _holds(rep):
    return [i["where"] for i in rep["issues"] if i["code"] == "dead_hold"]


@pytest.mark.parametrize("n", [31, 61, 121])
def test_slow_drift_is_not_a_dead_hold_at_any_fps(n):
    # 5 units/s on a 202-unit motion: slow but moving.
    assert _holds(analysis.motion_report(_sampled(5.0, n), loop=False)) == []


@pytest.mark.parametrize("n", [31, 61, 121])
def test_near_freeze_is_a_dead_hold_at_any_fps(n):
    assert _holds(analysis.motion_report(_sampled(1.0, n), loop=False)) == ["t=0.5 to t=1.0"]
