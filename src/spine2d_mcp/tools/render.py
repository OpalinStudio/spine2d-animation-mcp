"""MCP tools: render and check skeletons the way they will really look.

Two renderers, pick by purpose:

- `runtime_render` - the OFFICIAL Spine web runtime (spine-webgl, headless
  Chromium). Fast (seconds), no editor needed, and exactly what a web game
  (Pixi / Phaser / Spine Player...) draws: meshes, clipping, blend modes, tint
  black, IK / transform / path / physics constraints, sliders. Use it after
  every change to look at the result.
- `editor_render` - the Spine EDITOR's own export (needs Spine installed and
  licensed). Slower (it launches the editor) but it is the reference render,
  for final deliverables: GIF / APNG / WebM / MOV / AVI or PNG / WebP / JPEG
  sequences.

Plus `runtime_validate` (load the data in the official runtime = proof it
will load in the game), `export_web_preview` (one HTML file to open on a
phone) and `export_game_pack` (runtime files from the editor, with checks).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from ..cli import spine_cli as cli
from ..cli.editor_render import editor_render as _editor_render
from ..runtime import fetch
from ..runtime import render as rt_render
from ..runtime.web_preview import export_web_preview as _export_web_preview
from ._common import mcp, resolve


@mcp.tool()
def spine_runtime_setup(version: str | None = None, install_browser: bool = True) -> dict:
    """Download the official Spine web runtime (spine-webgl + spine-player,
    from npm, sha512-checked, cached outside the repo) and the headless
    Chromium used by runtime_render / runtime_validate / export_web_preview.
    version: "4.3" (newest 4.3.x, default) or an exact "4.3.13"; also settable
    with SPINE_RUNTIME_VERSION. Runs automatically on first use; call it to
    pre-install or to diagnose."""
    rt = fetch.ensure_runtime(version)
    out: dict = {"runtime": rt.as_dict(), "cache": str(fetch.cache_root())}
    if install_browser:
        p = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium-headless-shell"],
                           capture_output=True, text=True, timeout=1200)
        out["browser_install"] = {"ok": p.returncode == 0, "log": (p.stdout + p.stderr)[-1500:]}
    return out


@mcp.tool()
def runtime_validate(
    skeleton: str,
    atlas: str | None = None,
    skin: str | None = None,
    animation: str | None = None,
    runtime_version: str | None = None,
) -> dict:
    """Load a skeleton (.json or .skel) + atlas in the OFFICIAL Spine runtime
    and pose it once: if this passes, the game's Spine runtime will load it.
    Returns ok, or the stage that failed (load / parse / pose) with the
    runtime's own error message (e.g. "Region not found in atlas: arm"), plus
    what the runtime sees: bones, slots, skins, animations with durations,
    constraint counts (ik/transform/path/physics/slider), attachment types,
    atlas pages (size, premultiplied alpha), setup-pose bounds.
    The atlas defaults to <name>.atlas / <name>-pma.atlas next to the
    skeleton; without one, a temporary atlas is packed from skeleton.images.
    runtime_version: default = the data's own major.minor (4.2 export -> 4.2
    runtime, like a spine-pixi-v8 4.2 game), else 4.3; or "4.2.95" exactly."""
    return rt_render.validate(skeleton, atlas, skin, animation, runtime_version=runtime_version)


@mcp.tool()
def runtime_render(
    skeleton: str,
    output: str,
    format: Literal["png", "frames", "sheet", "gif", "apng", "webp", "mp4", "webm", "mov"] = "gif",
    animation: str | None = None,
    skin: str | None = None,
    time: float | None = None,
    fps: float = 30,
    duration: float | None = None,
    loops: int = 1,
    scale: float = 1.0,
    width: int | None = None,
    height: int | None = None,
    padding: float = 16,
    background: str | None = None,
    supersample: int = 2,
    warmup: float = 0,
    atlas: str | None = None,
    crop: dict | None = None,
    columns: int = 6,
    matte: str | None = None,
    runtime_version: str | None = None,
) -> dict:
    """Render with the OFFICIAL Spine web runtime (what the game will show,
    physics and clipping included), in seconds, without the editor.

    format: png (one frame at `time`, setup pose without animation), frames
    (folder of PNGs), sheet (contact sheet, checkerboard = transparency),
    gif, apng / webp (full alpha), mp4 (no alpha, on `background`), webm
    (VP9 + alpha), mov (ProRes 4444 + alpha for After Effects).
    Size: `scale` pixels per skeleton unit, or `width` and/or `height` to fit
    (exact canvas when both are given); for a sheet they size each cell
    (default 256 px wide). The framing is the union of the
    bounds over the whole animation (or `crop` = {x, y, width, height} in
    skeleton units). background: "#rrggbb[aa]" or None (transparent).
    warmup: number of animation loops played before capture so physics is
    already in motion (like the editor's Warm Up). supersample 2 = rendered
    at 2x then downscaled for clean edges. runtime_version: default = the
    data's major.minor (a 4.2 export renders with the 4.2 runtime). Returns
    the output path, size, frames, world bounds and what the runtime loaded."""
    return rt_render.render(
        skeleton, output, format=format, animation=animation, skin=skin, time=time, fps=fps,
        duration=duration, loops=loops, scale=scale, width=width, height=height, padding=padding,
        background=background, supersample=supersample, warmup=warmup, atlas=atlas, crop=crop,
        columns=columns, matte=matte, runtime_version=runtime_version,
    )


@mcp.tool()
def editor_render(
    input_path: str,
    output: str,
    format: Literal["png", "jpeg", "webp", "gif", "apng", "webm", "mov", "avi"] = "gif",
    animation: str | None = None,
    skin: str | None = None,
    skeleton_name: str | None = None,
    scale: float = 100,
    fps: float = 30,
    background: str | None = None,
    warm_up: int = 0,
    last_frame: bool = False,
    pose: bool = False,
    settings_overrides: dict | None = None,
    spine_path: str | None = None,
    version: str | None = None,
) -> dict:
    """Render with the Spine EDITOR (reference quality, needs Spine 4.3
    installed and activated). input_path: a .spine project, or a skeleton
    .json / .skel - imported into a THROWAWAY temp project, your files are
    never modified. format: gif / apng / webm / mov / avi = one file at
    `output`; png / jpeg / webp = one file per frame in the `output` folder.
    animation None = every animation; pose=True renders the setup pose.
    scale in percent. background "#rrggbb" or None (transparent where the
    format allows: png, webp, apng, gif 1-bit, webm, mov, avi).
    warm_up: loops played first so physics is in motion. settings_overrides:
    any editor export settings field (e.g. {"msaa": 8, "smoothing": 11})."""
    return _editor_render(
        input_path, output, format=format, animation=animation, skin=skin,
        skeleton_name=skeleton_name, scale=scale, fps=fps, background=background,
        warm_up=warm_up, last_frame=last_frame, pose=pose, settings_overrides=settings_overrides,
        spine_path=spine_path, version=version,
    )


@mcp.tool()
def export_web_preview(
    skeleton: str,
    output: str,
    atlas: str | None = None,
    animation: str | None = None,
    skin: str | None = None,
    background: str = "#1b1d22",
    title: str | None = None,
    single_file: bool = True,
    verify: bool = True,
    runtime_version: str | None = None,
) -> dict:
    """Build an HTML preview with the official Spine Web Player: buttons for
    every animation and skin, background switcher (game color / dark / light
    / checker), speed x0.25-x2 and loop toggle. single_file=True writes ONE
    self-contained .html (runtime + skeleton + atlas inlined) to send to a
    phone and open offline; False writes a folder (index.html + assets/).
    verify=True opens it headless at phone (390x844 @3x) and desktop
    (1440x900) sizes, checks the player started and saves both screenshots
    next to the page."""
    res = _export_web_preview(skeleton, output, atlas=atlas, animation=animation, skin=skin,
                              background=background, title=title, single_file=single_file,
                              runtime_version=runtime_version)
    if verify:
        html = Path(res["html"])
        shots_dir = html.parent / f"{html.stem}_screenshots"
        check = rt_render._run_worker({
            "mode": "page", "html": str(html), "out_dir": str(shots_dir),
            "viewports": [{"name": "phone", "width": 390, "height": 844, "scale": 3},
                          {"name": "desktop", "width": 1440, "height": 900, "scale": 1}],
        }, timeout=300)
        res["verified"] = check.get("ok", False)
        res["player_status"] = check.get("status") or check.get("error")
        res["screenshots"] = check.get("screenshots", [])
    return res


@mcp.tool()
def export_game_pack(
    project: str,
    output_dir: str,
    format: Literal["binary", "json"] = "binary",
    premultiplied_alpha: bool = True,
    max_page_size: int = 2048,
    scales: list[float] | None = None,
    scale_suffixes: list[str] | None = None,
    packing: Literal["rectangles", "polygons"] = "rectangles",
    images_dir: str | None = None,
    name: str | None = None,
    clean_up: bool = True,
    validate: bool = True,
    spine_path: str | None = None,
    version: str | None = None,
) -> dict:
    """Export the runtime files a game loads, with the Spine editor:
    skeleton data (.skel binary = smaller/faster, or .json) + texture atlas
    (.atlas + .png pages) packed by Spine's texture packer, optional extra
    resolutions (scales=[1, 0.5] -> name.atlas + name@0.5x.atlas), and
    premultiplied alpha on by default (Esoteric's recommendation for every
    runtime: Pixi, Phaser, Unity, Cocos, web player...).

    project: a .spine project, or a skeleton .json/.skel (imported into a
    throwaway project first; nothing of yours is modified). images_dir: the
    attachment images (default: skeleton.images of a JSON, or images/ next
    to the project). version: the editor version to run (`-u`, e.g. "4.3.26";
    the runtime major.minor of the game must match the export).
    validate=True loads each exported skeleton + atlas pair in the official
    runtime and reports the result."""
    src = resolve(project)
    out = resolve(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = name or src.stem
    imgs = resolve(images_dir) if images_dir else (
        rt_render._skeleton_images_dir(src) if src.suffix.lower() != ".spine"
        else (src.parent / "images" if (src.parent / "images").is_dir() else None))
    if imgs is None or not imgs.is_dir():
        return {"ok": False, "stage": "images",
                "error": "attachment images folder not found: pass images_dir"}
    sc = scales or [1]
    suffixes = scale_suffixes or ["" if s == 1 else f"@{s:g}x" for s in sc]
    pack = cli.pack_settings(
        premultiplyAlpha=premultiplied_alpha, bleed=not premultiplied_alpha,
        maxWidth=max_page_size, maxHeight=max_page_size, packing=packing,
        scale=sc, scaleSuffix=suffixes, scaleResampling=["bicubic"] * len(sc),
    )
    log: list[str] = []

    def keep(text: str) -> None:
        log.extend(ln for ln in text.splitlines() if ln.strip() and not ln.startswith("   ")
                   and "MSAA" not in ln and "NoSuchMethod" not in ln
                   and not ln.startswith(("Spine Launcher", "Esoteric", "Mac OS", "Licensed")))

    before = set(out.rglob("*"))
    with tempfile.TemporaryDirectory(prefix="spine-pack-") as tmp_s:
        proj = src
        if src.suffix.lower() != ".spine":
            proj = Path(tmp_s) / f"{stem}.spine"
            r = cli.import_data(str(src), str(proj), skeleton_name=stem, replace=True,
                                spine_path=spine_path, version_=version)
            keep(r.stdout)
            if not r.ok or not proj.exists():
                return {"ok": False, "stage": "import", "editor_log": log}
        # 1) skeleton data
        r = cli.export(str(proj), str(out), format, clean=clean_up, spine_path=spine_path,
                       version_=version)
        keep(r.stdout + r.stderr)
        if not r.ok:
            return {"ok": False, "stage": "export", "editor_log": log}
        # 2) atlas with explicit packer settings (-j: meshes -> polygon packing)
        r = cli.pack(str(imgs), str(out), name=stem, settings=pack, projects=[str(proj)],
                     spine_path=spine_path)
        keep(r.stdout + r.stderr)
    created = sorted(p for p in out.rglob("*") if p.is_file() and p not in before)
    res: dict = {"ok": r.ok and bool(created), "output_dir": str(out),
                 "files": [str(p) for p in created], "premultiplied_alpha": premultiplied_alpha,
                 "scales": dict(zip(suffixes, sc)), "editor_log": log[-14:]}
    pages = [p for p in created if p.suffix == ".png"]
    try:
        from PIL import Image

        res["texture_memory"] = {p.name: f"{Image.open(p).width}x{Image.open(p).height} = "
                                         f"{Image.open(p).width * Image.open(p).height * 4 / 1048576:.1f} MB RGBA"
                                 for p in pages}
    except Exception:
        pass
    if validate and created:
        ext = ".skel" if format == "binary" else ".json"
        checks = {}
        for sk in (p for p in created if p.suffix == ext):
            for at in (p for p in created if p.suffix == ".atlas"):
                key = f"{sk.name} + {at.name}"
                try:
                    v = rt_render.validate(str(sk), str(at))
                    checks[key] = {"ok": v.get("ok"), "error": v.get("error"),
                                   "runtime": v.get("runtime_version"),
                                   "pages": (v.get("info") or {}).get("atlasPages")}
                except Exception as e:  # report, don't hide the export result
                    checks[key] = {"ok": False, "error": str(e)}
        res["runtime_checks"] = checks
        res["ok"] = res["ok"] and bool(checks) and all(c["ok"] for c in checks.values())
    return res
