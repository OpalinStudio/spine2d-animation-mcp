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
