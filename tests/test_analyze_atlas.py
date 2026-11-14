"""analyze_animation on a working copy whose atlas is elsewhere: take `atlas`
(and `skin`) like runtime_render, and never say "no defect" when the runtime
part did not run."""

import json
import shutil

import pytest

from spine2d_mcp.runtime import render as rr
from spine2d_mcp.tools import quality


def _still_skeleton(tmp_path):
    """Two bones, an eased loop that the key checks find clean."""
    data = {
        "skeleton": {"spine": "4.3.26"},
        "bones": [{"name": "root"}, {"name": "body", "parent": "root"}],
        "slots": [],
        "skins": [{"name": "default", "attachments": {}}],
        "animations": {"idle": {"bones": {"body": {"rotate": [
            {"value": 0, "curve": [0.25, 0, 0.75, 4]},
            {"time": 0.5, "value": 4, "curve": [0.75, 4, 1.25, 0]},
            {"time": 1, "value": 0}]}}}},
    }
    p = tmp_path / "copy" / "sym.json"
    p.parent.mkdir()
    p.write_text(json.dumps(data))
    return p


def test_verdict_says_the_runtime_part_did_not_run(tmp_path, monkeypatch):
    sk = _still_skeleton(tmp_path)

    def boom(*a, **k):
        raise rr.RuntimeRenderError("no .atlas next to the skeleton and no images folder")

    monkeypatch.setattr(rr, "sample", boom)
    rep = quality.analyze_animation(str(sk), "idle")
    assert rep["motion"]["runtime_error"]
    assert "no defect" not in rep["verdict"]
    assert "runtime" in rep["verdict"] and "atlas" in rep["verdict"]
    assert any(i["code"] == "runtime_not_run" for i in rep["issues"])
    everything = quality.analyze_animation(str(sk))
    assert "no defect" not in everything["animations"][0]["verdict"]
    # runtime=False is a deliberate choice: no runtime issue invented.
    keys_only = quality.analyze_animation(str(sk), "idle", runtime=False)
    assert not any(i["code"] == "runtime_not_run" for i in keys_only["issues"])


def test_atlas_and_skin_are_passed_to_the_runtime(tmp_path, monkeypatch):
    sk = _still_skeleton(tmp_path)
    seen = {}

    def fake(skeleton, animation, **k):
        seen.update(k)
        return {"times": [0, 1], "tracks": {}, "events": []}

    monkeypatch.setattr(rr, "sample", fake)
    monkeypatch.setattr(quality.analysis, "motion_report", lambda *a, **k: {"issues": []})
    rep = quality.analyze_animation(str(sk), "idle", atlas="/elsewhere/sym.atlas", skin="jour")
    assert seen["atlas"] == "/elsewhere/sym.atlas" and seen["skin"] == "jour"
    assert "runtime_error" not in rep["motion"]


@pytest.fixture(scope="module")
def runtime_ok():
    from spine2d_mcp.runtime import fetch, worker

    try:
        fetch.ensure_runtime()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            worker._launch(p).close()
    except Exception as e:  # no network on first run, no Chromium...
        pytest.skip(f"official runtime not available: {e}")


@pytest.fixture
def rig_copy(synthetic_psd, tmp_path):
    """The JSON alone in another folder (a session copy), atlas left behind."""
    from spine2d_mcp.pipeline import import_psd_to_spine
    from spine2d_mcp.spine import document as doc
    from spine2d_mcp.spine import generators as gen

    res = import_psd_to_spine(synthetic_psd, str(tmp_path / "rig"), orient_bones=True)
    data = doc.load(res.project_path)
    gen.symbol_win(data, bone="torso")
    work = tmp_path / "work"
    work.mkdir()
    copy = work / "copy.json"
    doc.save(data, copy)
    atlas = next((tmp_path / "rig").glob("*.atlas"))
    return str(copy), str(atlas)


def test_real_runtime_with_an_atlas_elsewhere(runtime_ok, rig_copy):
    copy, atlas = rig_copy
    blind = quality.analyze_animation(copy, "win", fps=15)
    assert blind["motion"].get("runtime_error") and "no defect" not in blind["verdict"]
    seen = quality.analyze_animation(copy, "win", fps=15, atlas=atlas)
    assert "runtime_error" not in seen["motion"], seen["motion"]
    assert seen["motion"]["most_active"]
