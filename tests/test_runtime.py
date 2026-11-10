"""Official-runtime integration: download checks (offline, mocked) and real
headless renders (skipped when the runtime / Chromium can't be obtained)."""

import base64
import hashlib
import io
import json
import tarfile

import pytest

from spine2d_mcp.runtime import fetch
from spine2d_mcp.runtime import render as rr
from spine2d_mcp.runtime import worker


# ------------------------------------------------------------ fetch (offline)
def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINE_MCP_CACHE", str(tmp_path / "cache"))
    blobs = {
        "spine-webgl": _tarball({"package/dist/iife/spine-webgl.js": b"// webgl"}),
        "spine-player": _tarball({"package/dist/iife/spine-player.min.js": b"// player",
                                  "package/dist/spine-player.css": b"/* css */"}),
    }
    state = {"corrupt": False}

    def get(url, timeout=60):
        if url.endswith("/@esotericsoftware%2Fspine-webgl"):
            return json.dumps({"versions": {"4.2.99": {}, "4.3.9": {}, "4.3.13": {}, "4.4.0-beta": {}}}).encode()
        if "/LICENSE" in url:
            return b"Spine Runtimes License Agreement"
        for name, blob in blobs.items():
            if url.endswith(f"%2F{name}/4.3.13"):
                digest = base64.b64encode(hashlib.sha512(blob).digest()).decode()
                if state["corrupt"]:
                    digest = "x" + digest[1:]
                return json.dumps({"dist": {"tarball": f"https://t/{name}.tgz",
                                            "integrity": f"sha512-{digest}"}}).encode()
            if url == f"https://t/{name}.tgz":
                return blob
        raise AssertionError(url)

    monkeypatch.setattr(fetch, "_get", get)
    return state


def test_resolves_newest_patch_of_the_line(fake_registry):
    assert fetch.resolve_version("4.3") == "4.3.13"
    assert fetch.resolve_version("4.3.9") == "4.3.9"


def test_downloads_extracts_and_caches(fake_registry, monkeypatch):
    rt = fetch.ensure_runtime("4.3")
    assert rt.version == "4.3.13"
    assert rt.webgl_js.read_bytes() == b"// webgl" and rt.player_css.exists() and rt.license.exists()
    # Offline afterwards: the cached version is used.
    monkeypatch.setattr(fetch, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert fetch.ensure_runtime("4.3").version == "4.3.13"


def test_integrity_mismatch_is_refused(fake_registry):
    fake_registry["corrupt"] = True
    with pytest.raises(fetch.RuntimeFetchError, match="integrity"):
        fetch.ensure_runtime("4.3")


# ------------------------------------------------------------ pure helpers
def test_view_fit_and_scale():
    b = {"x": -50, "y": 0, "width": 100, "height": 200}
    v = worker._view({"width": 232, "height": 432, "padding": 16, "supersample": 2}, b)
    assert (v["outW"], v["outH"]) == (232, 432) and v["scale"] == pytest.approx(2)
    assert v["cx"] == 0 and v["cy"] == 100 and (v["pxW"], v["pxH"]) == (464, 864)
    v = worker._view({"scale": 0.5, "padding": 0}, b)
    assert (v["outW"], v["outH"]) == (50, 100)


def test_times_cover_the_loop_without_duplicate_last_frame():
    info = {"animations": [{"name": "win", "duration": 1.0}]}
    times, fps = worker._times({"animation": "win", "fps": 10}, info)
    assert times == pytest.approx([i / 10 for i in range(10)])
    times, _ = worker._times({"animation": "win", "fps": 10, "include_last": True, "loops": 2}, info)
    assert len(times) == 21 and times[-1] == pytest.approx(2.0)


def test_fs_url_roundtrip(tmp_path):
    p = tmp_path / "dir with space" / "hero.json"
    url = worker.fs_url(p)
    from urllib.parse import unquote, urlparse

    assert worker._fs_path(unquote(urlparse(url).path)) == p.resolve()


def test_find_atlas_prefers_pma_and_exported_names(tmp_path):
    sk = tmp_path / "coin-pro.json"
    sk.write_text("{}")
    (tmp_path / "coin.atlas").write_text("")
    assert rr.find_atlas(sk) == tmp_path / "coin.atlas"
    (tmp_path / "coin-pma.atlas").write_text("")
    assert rr.find_atlas(sk) == tmp_path / "coin-pma.atlas"


# ------------------------------------------------------------ real renders
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
def rig(synthetic_psd, tmp_path):
    from spine2d_mcp.pipeline import import_psd_to_spine
    from spine2d_mcp.spine import document as doc
    from spine2d_mcp.spine import generators as gen

    res = import_psd_to_spine(synthetic_psd, str(tmp_path / "rig"), orient_bones=True)
    data = doc.load(res.project_path)
    gen.symbol_win(data, bone="torso")
    doc.save(data, res.project_path)
    return res.project_path


def test_runtime_validate_real(runtime_ok, rig):
    v = rr.validate(rig)
    assert v["ok"], v
    assert v["info"]["bones"] >= 10 and any(a["name"] == "win" for a in v["info"]["animations"])


def test_runtime_validate_reports_missing_region(runtime_ok, rig, tmp_path):
    data = json.loads(open(rig).read())
    data["skins"][0]["attachments"]["head"]["ghost"] = {"width": 10, "height": 10}
    data["slots"][0]["attachment"] = "ghost"
    bad = tmp_path / "rig" / "bad.json"
    bad.write_text(json.dumps(data))
    v = rr.validate(str(bad), atlas=str(tmp_path / "rig" / "test_character.atlas"))
    assert not v["ok"] and v["stage"] == "parse" and "ghost" in v["error"]


@pytest.mark.parametrize("fmt", ["png", "gif", "sheet", "apng"])
def test_runtime_render_formats(runtime_ok, rig, tmp_path, fmt):
    from PIL import Image

    out = tmp_path / f"out.{'png' if fmt in ('png', 'sheet', 'apng') else fmt}"
    res = rr.render(rig, str(out), format=fmt, animation=None if fmt == "png" else "win",
                    fps=10, width=200)
    assert out.exists() and res["frames"] == (1 if fmt == "png" else 12)
    with Image.open(out) as im:
        if fmt in ("png", "gif", "apng"):
            assert im.size == (200, res["size"][1])
        if fmt in ("gif", "apng"):
            assert getattr(im, "n_frames", 1) == 12
    if fmt == "png":
        alpha = Image.open(out).getchannel("A")
        assert alpha.getextrema() == (0, 255)  # transparent around, opaque art


# ------------------------------------------------- motion, review renders
@pytest.fixture
def walker(make_psd, tmp_path):
    """Humanoid with knees on IK legs, a planted walk and a footstep event."""
    from spine2d_mcp.pipeline import import_psd_to_spine
    from spine2d_mcp.spine import animation as an
    from spine2d_mcp.spine import document as doc

    res = import_psd_to_spine(make_psd([
        ("head", 160, 20, 80, 80), ("body", 150, 110, 100, 180),
        ("leg_left", 150, 300, 45, 95), ("shin_left", 150, 395, 45, 90), ("foot_left", 150, 480, 70, 28),
        ("leg_right", 205, 300, 45, 95), ("shin_right", 205, 395, 45, 90), ("foot_right", 205, 480, 70, 28),
    ]), str(tmp_path / "walker"), ik_legs=True, animations=["walk"], export_images=True)
    data = doc.load(res.project_path)
    doc.set_event(data, "footstep")
    an.set_event_keys(data["animations"]["walk"], [{"time": 0.25, "name": "footstep"}])
    an.set_keys(data["animations"].setdefault("low", {}), "bone", "head", "rotate", [{"value": 0}, {"time": 1, "value": 0}])
    an.set_keys(data["animations"].setdefault("high", {}), "bone", "head", "rotate", [{"value": 40}, {"time": 1, "value": 40}])
    doc.save(data, res.project_path)
    return str(res.project_path)


def test_walk_on_ik_legs_really_moves_them_in_the_runtime(runtime_ok, walker):
    s = rr.sample(walker, "walk", bones=["leg_left", "shin_left", "shin_left-ik-target"], fps=20)
    assert s["times"][0] == 0 and s["times"][-1] == pytest.approx(1.0) and len(s["times"]) == 21
    thigh, shin = s["tracks"]["leg_left"]["rotation"], s["tracks"]["shin_left"]["rotation"]
    assert max(thigh) - min(thigh) > 30  # the IK solver swings the leg after its target
    assert max(a - b for a, b in zip(thigh, shin)) > 20  # ...and the knee folds forward
    target = s["tracks"]["shin_left-ik-target"]
    stance = [y for t, y in zip(s["times"], target["y"]) if 0.25 <= t <= 0.8]
    assert max(stance) - min(stance) < 0.01
    assert s["events"] == [{"time": 0.25, "name": "footstep", "track": 0, "animation": "walk"}]


def test_track_zero_overlay_crossfades_with_mix(runtime_ok, walker):
    def head(mix):
        s = rr.sample(walker, "low", bones=["head"], times=[0.4, 0.6, 0.9], loop=True,
                      overlays=[{"track": 0, "animation": "high", "start": 0.5, "loop": True, "mix": mix}])
        return [r - s["tracks"]["head"]["rotation"][0] for r in s["tracks"]["head"]["rotation"]]

    assert head(0) == pytest.approx([0, 40, 40], abs=0.01)  # a cut
    _, mid, end = head(0.2)
    assert 10 < mid < 30 and end == pytest.approx(40, abs=0.01)  # halfway through the crossfade


def test_onion_render_with_bone_trails_and_preview(runtime_ok, walker, tmp_path):
    from PIL import Image

    out, preview = tmp_path / "walk_onion.png", tmp_path / "preview.jpg"
    res = rr.render(walker, str(out), format="onion", animation="walk", fps=10, width=300,
                    track_bones=["head", "shin_left-ik-target"], background="#202020",
                    preview=str(preview))
    assert res["frames"] == 10 and list(res["tracks"]) == ["head", "shin_left-ik-target"]
    assert len(res["tracks"]["head"]["x"]) == 10 and res["events"][0]["name"] == "footstep"
    with Image.open(out) as im:
        assert im.size == tuple(res["size"])
        colors = {c for _, c in im.convert("RGB").getcolors(1 << 20)}
        assert (255, 64, 129) in colors and (0, 229, 255) in colors  # one trail color per bone
    with Image.open(preview) as im:
        assert im.format == "JPEG" and max(im.size) <= 1568


def test_debug_overlay_draws_the_bones(runtime_ok, walker, tmp_path):
    from PIL import Image, ImageChops

    plain = rr.render(walker, str(tmp_path / "plain.png"), format="png", width=300)
    debug = rr.render(walker, str(tmp_path / "debug.png"), format="png", width=300, debug=True)
    assert plain["size"] == debug["size"]
    a, b = (Image.open(tmp_path / n).convert("RGB") for n in ("plain.png", "debug.png"))
    diff = ImageChops.difference(a, b)
    assert diff.getbbox() is not None
    assert (255, 0, 0) in {c for _, c in b.getcolors(1 << 20)}  # bone lines


def test_runtime_render_tool_returns_the_picture(runtime_ok, walker, tmp_path):
    import asyncio

    from PIL import Image

    from spine2d_mcp.tools import mcp

    content = asyncio.run(mcp.call_tool("runtime_render", {
        "skeleton": walker, "output": str(tmp_path / "walk.gif"), "animation": "walk",
        "fps": 10, "width": 120}))
    report, picture = content
    info = json.loads(report.text)
    assert info["format"] == "gif" and info["frames"] == 10 and "preview" not in info
    assert picture.type == "image" and picture.mimeType == "image/jpeg"
    with Image.open(io.BytesIO(base64.b64decode(picture.data))) as im:
        assert im.size == (6 * 120, 2 * info["size"][1])  # a contact sheet of the 10 frames


def test_analyze_animation_tool_merges_keys_and_runtime_review(runtime_ok, walker):
    from spine2d_mcp.tools import quality

    rep = quality.analyze_animation(walker, "walk", ground_bones=["shin_left-ik-target"])
    assert rep["loop"]["assumed"] and not [i for i in rep["issues"] if i["severity"] == "warning"], rep["issues"]
    motion = rep["motion"]
    assert motion["contacts"] and motion["events_fired"][0]["name"] == "footstep"
    # The ground speed measured in the runtime is the one the generator announced.
    assert motion["ground_speed"] == pytest.approx(
        2 * 185 * 0.4226 / 0.55, rel=0.05)
    everything = quality.analyze_animation(walker, runtime=False)
    assert [a["animation"] for a in everything["animations"]] == ["high", "low", "walk"]
