"""Headless runtime worker: renders / validates a skeleton with the official
spine-webgl runtime inside headless Chromium (Playwright).

Runs as a subprocess (`python -m spine2d_mcp.runtime.worker`): the request is
a JSON object on stdin, the result a JSON object on stdout. A separate process
keeps Playwright's own event loop away from the MCP server's asyncio loop and
lets the parent enforce a timeout.

Files are served to the page from a virtual origin (http://spine.local) by
request interception, so no local HTTP server and no file:// restrictions:

    /page/<file>   this package's page/ folder (render.html, render.js)
    /rt/<file>     the cached Spine runtime (spine-webgl.js)
    /fs/<path>     any file on disk, by absolute path (skeleton, atlas, pages)
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

PAGE_DIR = Path(__file__).parent / "page"
ORIGIN = "http://spine.local"
MAX_FRAMES = 900
MAX_SIDE = 4096
MAX_PIXELS_SIDE = 8192

CONTENT_TYPES = {
    ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".atlas": "text/plain", ".txt": "text/plain",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".skel": "application/octet-stream",
}


def fs_url(path: str | os.PathLike) -> str:
    p = Path(path).resolve().as_posix().lstrip("/")
    return f"{ORIGIN}/fs/{quote(p)}"


def _fs_path(url_path: str) -> Path:
    p = url_path[len("/fs/"):]
    if not re.match(r"^[A-Za-z]:", p):
        p = "/" + p
    return Path(p)


def _browser_candidates() -> list[str]:
    """Already-downloaded Playwright Chromium builds, newest first (used when
    the build pinned by the installed Playwright is missing)."""
    roots = []
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        roots.append(Path(env))
    home = Path.home()
    roots += [home / "Library" / "Caches" / "ms-playwright", home / ".cache" / "ms-playwright",
              Path(os.environ.get("LOCALAPPDATA", home)) / "ms-playwright"]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
            if not d.name.startswith(("chromium_headless_shell-", "chromium-")):
                continue
            for pattern in ("*/chrome-headless-shell", "*/chrome-headless-shell.exe",
                            "*/Chromium.app/Contents/MacOS/Chromium",
                            "*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                            "*/chrome", "*/chrome.exe"):
                found += [str(p) for p in d.glob(pattern) if p.is_file()]
    return found


# GPU first (Metal on macOS: ~100x faster than software for big frames),
# SwiftShader (CPU) as the always-available fallback. SPINE_MCP_GL=software
# forces the fallback, e.g. on a headless Linux server without GPU.
SOFTWARE_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def launch_args() -> list[list[str]]:
    import platform

    if os.environ.get("SPINE_MCP_GL", "").lower() == "software":
        return [SOFTWARE_ARGS]
    gpu = ["--use-angle=metal"] if platform.system() == "Darwin" else ["--ignore-gpu-blocklist"]
    return [gpu + ["--enable-unsafe-swiftshader"], SOFTWARE_ARGS]


def _launch(p):
    first = None
    for args in launch_args():
        try:
            return p.chromium.launch(args=args)
        except Exception as e:
            first = first or e
            for exe in _browser_candidates():
                try:
                    return p.chromium.launch(executable_path=exe, args=args)
                except Exception:
                    continue
    if first is not None:
        raise RuntimeError(
            "No headless Chromium available for the Spine runtime renderer. Run the "
            "`spine_runtime_setup` tool (or `uv run playwright install chromium-headless-shell`). "
            f"Playwright said: {str(first).splitlines()[0]}"
        ) from first
    raise RuntimeError("no browser launch configuration")


def _parse_color(c):
    if c is None:
        return None
    if isinstance(c, (list, tuple)):
        v = [float(x) for x in c] + [1.0] * (4 - len(c))
        return [x / 255 if max(v) > 1 else x for x in v][:4]
    h = str(c).lstrip("#")
    if len(h) == 6:
        h += "ff"
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4, 6)]


def _times(req: dict, info: dict) -> tuple[list[float], float]:
    fps = float(req.get("fps") or 30)
    anim = req.get("animation")
    if req.get("time") is not None or not anim:
        return [float(req.get("time") or 0.0)], fps
    dur = req.get("duration")
    if dur is None:
        dur = next((a["duration"] for a in info["animations"] if a["name"] == anim), 0.0)
    dur = float(dur) * max(1, int(req.get("loops") or 1))
    n = max(1, int(round(dur * fps)))
    times = [i / fps for i in range(n)]
    if req.get("include_last") and dur > 0:
        times.append(dur)
    if len(times) > MAX_FRAMES:
        raise ValueError(f"{len(times)} frames requested (max {MAX_FRAMES}): lower fps or duration")
    return times, fps


def _view(req: dict, bounds: dict) -> dict:
    pad = float(req.get("padding", 16))
    bw, bh = max(bounds["width"], 1e-3), max(bounds["height"], 1e-3)
    W, H = req.get("width"), req.get("height")
    if W and H:
        s = min((W - 2 * pad) / bw, (H - 2 * pad) / bh)
    elif W:
        s = (W - 2 * pad) / bw
        H = math.ceil(bh * s + 2 * pad)
    elif H:
        s = (H - 2 * pad) / bh
        W = math.ceil(bw * s + 2 * pad)
    else:
        s = float(req.get("scale") or 1.0)
        W, H = math.ceil(bw * s + 2 * pad), math.ceil(bh * s + 2 * pad)
    if s <= 0:
        raise ValueError("padding leaves no room for the skeleton")
    if max(W, H) > MAX_SIDE:
        k = MAX_SIDE / max(W, H)
        W, H, s, pad = math.ceil(W * k), math.ceil(H * k), s * k, pad * k
    ss = max(1, int(req.get("supersample") or 1))
    while ss > 1 and max(W, H) * ss > MAX_PIXELS_SIDE:
        ss -= 1
    return {
        "cx": bounds["x"] + bw / 2, "cy": bounds["y"] + bh / 2,
        "worldW": W / s, "worldH": H / s,
        "pxW": int(W * ss), "pxH": int(H * ss),
        "outW": int(W), "outH": int(H), "scale": s, "supersample": ss,
        "background": _parse_color(req.get("background")),
    }


def _save_frame(url: str, view: dict, path: Path) -> None:
    from PIL import Image

    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA")
    if img.size != (view["outW"], view["outH"]):
        # Resample premultiplied so transparent edges don't go dark.
        img = img.convert("RGBa").resize((view["outW"], view["outH"]), Image.Resampling.LANCZOS).convert("RGBA")
    img.save(path, compress_level=3)


def _check_page(browser, req: dict, route) -> dict:
    """Open an exported HTML preview at each viewport, wait for the player,
    and screenshot it. Viewports: [{"name", "width", "height", "scale"}]."""
    html_url = fs_url(req["html"])
    shots, statuses = [], {}
    for vp in req.get("viewports") or [{"name": "phone", "width": 390, "height": 844, "scale": 3}]:
        ctx = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]},
                                  device_scale_factor=vp.get("scale", 1))
        page = ctx.new_page()
        logs: list[str] = []
        page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
        page.route(f"{ORIGIN}/**", route)
        page.goto(html_url)
        try:
            page.wait_for_function("window.__spineMcpStatus !== undefined", timeout=30000)
            status = page.evaluate("window.__spineMcpStatus")
        except Exception as e:
            status = f"error: player did not start ({e.__class__.__name__})"
        page.wait_for_timeout(int(req.get("settle_ms", 1200)))
        out = Path(req["out_dir"]) / f"preview_{vp['name']}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        shots.append(str(out))
        statuses[vp["name"]] = status if not logs else f"{status} | {'; '.join(logs[-3:])}"
        ctx.close()
    ok = all(s.startswith("ok") and "pageerror" not in s for s in statuses.values())
    return {"ok": ok, "status": statuses, "screenshots": shots}


def handle(req: dict) -> dict:
    from playwright.sync_api import sync_playwright

    rt_dir = Path(req.get("runtime_dir") or ".")
    page_mode = req.get("mode") == "page"
    skeleton = Path(req["skeleton"]).resolve() if not page_mode else Path(".")
    atlas = Path(req["atlas"]).resolve() if not page_mode else Path(".")
    binary = skeleton.suffix.lower() == ".skel"

    def route(r):
        path = unquote(urlparse(r.request.url).path)
        if path.startswith("/page/"):
            f = PAGE_DIR / path[len("/page/"):]
        elif path.startswith("/rt/"):
            f = rt_dir / path[len("/rt/"):]
        elif path.startswith("/fs/"):
            f = _fs_path(path)
        else:
            return r.fulfill(status=404, body="not found")
        if not f.is_file():
            return r.fulfill(status=404, body=f"missing file: {f}")
        r.fulfill(status=200, body=f.read_bytes(),
                  headers={"content-type": CONTENT_TYPES.get(f.suffix.lower(), "application/octet-stream"),
                           "access-control-allow-origin": "*"})

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            if req.get("mode") == "page":
                return _check_page(browser, req, route)
            page = browser.new_page()
            logs: list[str] = []
            page.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
            page.route(f"{ORIGIN}/**", route)
            page.goto(f"{ORIGIN}/page/render.html")
            page.wait_for_function("window.spineMcpReady === true", timeout=30000)
            res = page.evaluate("c => window.spineMcp.load(c)", {
                "skeleton": fs_url(skeleton), "atlas": fs_url(atlas), "binary": binary,
                "dataScale": req.get("data_scale") or 1, "skin": req.get("skin"),
                "animation": req.get("animation"), "loop": req.get("loop", True),
            })
            res["runtime_version"] = req.get("runtime_version")
            if logs:
                res["console"] = logs[-20:]
            if not res.get("ok") or req.get("mode") == "validate":
                return res
            times, fps = _times(req, res["info"])
            warmup = float(req.get("warmup") or 0)
            bounds = req.get("crop")
            if not bounds:
                bounds = page.evaluate("a => window.spineMcp.measure(a[0], a[1], a[2])", [times, fps, warmup])
            if not bounds:
                d = res["info"]
                bounds = {"x": d["x"], "y": d["y"], "width": d["width"] or 100, "height": d["height"] or 100}
            view = _view(req, bounds)
            out_dir = Path(req["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            prefix = req.get("prefix", "frame_")
            page.evaluate("a => window.spineMcp.begin(a[0], a[1], a[2], a[3])", [times, fps, warmup, view])
            # Frames per round trip: ~8 MB of PNG data at most.
            batch = max(1, min(16, int(8e6 / max(1, view["outW"] * view["outH"]))))
            frames: list[str] = []
            while len(frames) < len(times):
                urls = page.evaluate("n => window.spineMcp.next(n)", batch)
                if not urls:
                    break
                for u in urls:
                    path = out_dir / f"{prefix}{len(frames):04d}.png"
                    _save_frame(u, view, path)
                    frames.append(str(path))
            res.update(bounds=bounds, view=view, times=times, fps=fps, frames=frames)
            if logs:
                res["console"] = logs[-20:]
            return res
        finally:
            browser.close()


def main() -> None:
    req = json.loads(sys.stdin.read())
    try:
        out = handle(req)
    except Exception as e:  # report, never hang the parent
        out = {"ok": False, "stage": "worker", "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
