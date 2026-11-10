"""Render and validate skeletons with the official Spine runtime.

`render()` / `validate()` run `spine2d_mcp.runtime.worker` (headless Chromium
+ spine-webgl) in a subprocess and turn the frames into the requested output:

    png     one frame (`time`, setup pose without animation)
    frames  a folder of PNG frames
    sheet   a contact sheet (checkerboard behind transparent pixels)
    onion   one still of the whole motion: ghosted frames + bone trails
    gif     animated GIF (1-bit alpha: edges matted on `matte`)
    apng    animated PNG, full alpha
    webp    animated WebP, full alpha
    mp4     H.264 (no alpha: flattened on `background`, black by default)
    webm    VP9 with alpha
    mov     ProRes 4444 with alpha (After Effects / Premiere)

Video formats need ffmpeg on the PATH (or FFMPEG / SPINE_MCP_FFMPEG).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .fetch import ensure_runtime

FORMATS = ("png", "frames", "sheet", "onion", "gif", "apng", "webp", "mp4", "webm", "mov")
NOISE = ("GPU stall due to ReadPixels",)


class RuntimeRenderError(RuntimeError):
    pass


# ----------------------------------------------------------------- inputs
def _skeleton_images_dir(skeleton: Path) -> Path | None:
    if skeleton.suffix.lower() == ".json":
        try:
            data = json.loads(skeleton.read_text(encoding="utf-8"))
            rel = (data.get("skeleton") or {}).get("images")
            if rel:
                d = (skeleton.parent / rel).resolve()
                if d.is_dir():
                    return d
        except (OSError, ValueError):
            pass
    d = skeleton.parent / "images"
    return d if d.is_dir() else None


def find_atlas(skeleton: Path, atlas: str | None = None, prefer_pma: bool = True) -> Path | None:
    """Explicit atlas, else `<stem>.atlas` / `<stem>-pma.atlas` next to the
    skeleton (also without the `-pro`/`-ess` suffix of exported names), else
    the only .atlas of the folder."""
    if atlas:
        p = Path(atlas).expanduser().resolve()
        if not p.is_file():
            raise RuntimeRenderError(f"atlas not found: {p}")
        return p
    d, stem = skeleton.parent, skeleton.stem
    stems = [stem]
    for suf in ("-pro", "-ess"):
        if stem.endswith(suf):
            stems.append(stem[: -len(suf)])
    names = []
    for s in stems:
        pair = [f"{s}-pma.atlas", f"{s}.atlas"]
        names += pair if prefer_pma else pair[::-1]
    for n in names:
        if (d / n).is_file():
            return d / n
    all_atlases = sorted(d.glob("*.atlas"))
    return all_atlases[0] if len(all_atlases) == 1 else None


def resolve_inputs(skeleton: str, atlas: str | None, work: Path) -> tuple[Path, Path, str]:
    """(skeleton, atlas, how). Packs a temporary atlas from the images folder
    when the skeleton has no atlas yet (rigs being built with these tools)."""
    sk = Path(skeleton).expanduser().resolve()
    if not sk.is_file():
        raise RuntimeRenderError(f"skeleton not found: {sk}")
    found = find_atlas(sk, atlas)
    if found:
        return sk, found, "atlas"
    images = _skeleton_images_dir(sk)
    if not images:
        raise RuntimeRenderError(
            "no .atlas next to the skeleton and no images folder: pass `atlas`, or pack one "
            "with pack_atlas / spine_pack")
    from ..atlas.writer import pack_folder

    atlas_path, _, _ = pack_folder(images, work / "atlas", sk.stem, max_size=4096)
    return sk, atlas_path, f"packed from {images}"


def data_version(skeleton: Path) -> str | None:
    """Spine version that wrote the data: skeleton.spine of a JSON, or the
    version string after the 8-byte hash of a 4.x .skel."""
    try:
        if skeleton.suffix.lower() == ".json":
            return (json.loads(skeleton.read_text(encoding="utf-8")).get("skeleton") or {}).get("spine")
        with open(skeleton, "rb") as f:
            head = f.read(64)
        n, shift, i = 0, 0, 8
        while i < len(head):
            b = head[i]
            n |= (b & 0x7F) << shift
            i += 1
            if not b & 0x80:
                break
            shift += 7
        if n > 1:
            v = head[i:i + n - 1].decode("utf-8", "replace")
            if v[:1].isdigit():
                return v
    except (OSError, ValueError):
        pass
    return None


def runtime_line_for(skeleton: Path, explicit: str | None = None) -> str | None:
    """Runtime to load this data with: explicit > SPINE_RUNTIME_VERSION >
    the data's own major.minor (4.2 data -> 4.2 runtime) > default 4.3."""
    if explicit:
        return explicit
    if os.environ.get("SPINE_RUNTIME_VERSION"):
        return None
    v = data_version(skeleton)
    if v and v.count(".") >= 1:
        line = ".".join(v.split(".")[:2])
        if line in ("4.1", "4.2", "4.3"):
            return line
    return None


# ----------------------------------------------------------------- worker
def _run_worker(req: dict, timeout: float) -> dict:
    try:
        p = subprocess.run(
            [sys.executable, "-m", "spine2d_mcp.runtime.worker"],
            input=json.dumps(req), capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeRenderError(f"runtime renderer timed out after {timeout}s") from e
    try:
        res = json.loads(p.stdout)
    except ValueError as e:
        raise RuntimeRenderError(f"runtime renderer crashed: {(p.stderr or p.stdout)[-1500:]}") from e
    if res.get("console"):
        res["console"] = [m for m in res["console"] if not any(n in m for n in NOISE)] or None
        if res["console"] is None:
            res.pop("console")
    return res


def validate(skeleton: str, atlas: str | None = None, skin: str | None = None,
             animation: str | None = None, timeout: float = 300,
             runtime_version: str | None = None) -> dict:
    """Load the skeleton in the official runtime and pose it once."""
    with tempfile.TemporaryDirectory(prefix="spine-mcp-") as tmp:
        sk, at, how = resolve_inputs(skeleton, atlas, Path(tmp))
        rt = ensure_runtime(runtime_line_for(sk, runtime_version))
        res = _run_worker({
            "mode": "validate", "runtime_dir": str(rt.dir), "runtime_version": rt.version,
            "skeleton": str(sk), "atlas": str(at), "skin": skin, "animation": animation,
        }, timeout)
    res.update(skeleton=str(sk), atlas=str(at) if how == "atlas" else None, atlas_source=how,
               runtime_version=rt.version)
    return res


# ----------------------------------------------------------------- outputs
def _ffmpeg() -> str:
    exe = os.environ.get("SPINE_MCP_FFMPEG") or os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise RuntimeRenderError("ffmpeg not found (needed for mp4/webm/mov): install it or set FFMPEG")
    return exe


def _rgba(c: str | None, default=(0, 0, 0, 0)) -> tuple[int, int, int, int]:
    if not c:
        return default
    h = c.lstrip("#")
    if len(h) == 6:
        h += "ff"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def _load(frames: list[str]):
    from PIL import Image

    return [Image.open(f).convert("RGBA") for f in frames]


def _flatten(img, color):
    from PIL import Image

    base = Image.new("RGBA", img.size, color)
    base.alpha_composite(img)
    return base


def _gif(frames, out: Path, fps: float, background: str | None, matte: str | None, loop: int) -> None:
    from PIL import Image

    pal_frames = []
    for im in frames:
        if background:
            p = _flatten(im, _rgba(background)).convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT)
        else:
            m = _rgba(matte or "#000000")
            solid = _flatten(im, (m[0], m[1], m[2], 255)).convert("RGB")
            p = solid.quantize(255, method=Image.Quantize.MEDIANCUT)
            pal = (p.getpalette() or [])[: 255 * 3]
            p.putpalette(pal + [0, 0, 0] * (256 - len(pal) // 3))
            hole = im.getchannel("A").point(lambda a: 255 if a < 128 else 0)
            p.paste(255, mask=hole)
            p.info["transparency"] = 255
        pal_frames.append(p)
    kw: dict[str, Any] = dict(save_all=True, append_images=pal_frames[1:], duration=round(1000 / fps),
                              loop=loop, disposal=2, optimize=False)
    if not background:
        kw["transparency"] = 255
    pal_frames[0].save(out, **kw)


def _checker(size: tuple[int, int], tile: int = 12):
    from PIL import Image, ImageDraw

    w, h = size
    checker = Image.new("RGBA", (w, h), (205, 205, 205, 255))
    d = ImageDraw.Draw(checker)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            if (x // tile + y // tile) % 2:
                d.rectangle([x, y, x + tile - 1, y + tile - 1], fill=(160, 160, 160, 255))
    return checker


def _sheet(frames, times, out: Path, columns: int, background: str | None, label: bool) -> None:
    from PIL import Image, ImageDraw

    w, h = frames[0].size
    cols = max(1, min(columns, len(frames)))
    rows = -(-len(frames) // cols)
    sheet = Image.new("RGBA", (cols * w, rows * h), (38, 40, 46, 255))
    checker = _checker((w, h))
    for i, (im, t) in enumerate(zip(frames, times)):
        cell = _flatten(im, _rgba(background)) if background else Image.alpha_composite(checker, im)
        if label:
            ImageDraw.Draw(cell).text((4, 3), f"{i}  t={t:.3f}s", fill=(255, 40, 120, 255))
        sheet.alpha_composite(cell, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)


TRAIL_COLORS = ((255, 64, 129), (0, 229, 255), (255, 214, 0), (118, 255, 3), (255, 145, 0),
                (213, 0, 249), (29, 233, 182), (255, 255, 255))


def _pick(n: int, count: int) -> list[int]:
    """`count` indices spread over range(n), first and last included."""
    count = max(1, min(count, n))
    if count == 1:
        return [0]
    return sorted({round(i * (n - 1) / (count - 1)) for i in range(count)})


def _onion(frames, times, out: Path, background: str | None, ghosts: int, tracks: dict | None,
           view: dict) -> None:
    """One still image of the whole motion: `ghosts` frames stacked from
    faint (first) to opaque (last), plus the path of each tracked bone with a
    dot per frame. The dot spacing IS the timing: close dots = slow, wide
    dots = fast; a smooth curve = a clean arc."""
    from PIL import Image, ImageDraw

    w, h = frames[0].size
    base = Image.new("RGBA", (w, h), _rgba(background, (38, 40, 46, 255)))
    shown = _pick(len(frames), ghosts)
    for n, i in enumerate(shown):
        k = 1.0 if len(shown) == 1 else 0.16 + 0.84 * (n / (len(shown) - 1)) ** 1.6
        ghost = frames[i].copy()
        ghost.putalpha(ghost.getchannel("A").point(lambda a, k=k: round(a * k)))
        base.alpha_composite(ghost)
    if tracks:
        d = ImageDraw.Draw(base)
        s = view["outW"] / view["worldW"]
        x0, y1 = view["cx"] - view["worldW"] / 2, view["cy"] + view["worldH"] / 2
        for n, (bone, tr) in enumerate(tracks.items()):
            color = TRAIL_COLORS[n % len(TRAIL_COLORS)]
            pts = [((x - x0) * s, (y1 - y) * s) for x, y in zip(tr["x"], tr["y"])]
            if len(pts) > 1:
                d.line(pts, fill=color + (255,), width=2)
            for i, (px, py) in enumerate(pts):
                r = 4 if i in shown else 2
                d.ellipse([px - r, py - r, px + r, py + r], fill=color + (255,), outline=(0, 0, 0, 255))
            d.text((6, 4 + 12 * n), bone, fill=color + (255,))
    base.save(out)


def _tracks(samples: dict | None, wanted: list[str] | None) -> dict | None:
    """{bone: {x, y, rotation, scaleX, scaleY}} lists (one value per frame)."""
    if not samples or not samples.get("bones"):
        return None
    names = samples["bones"]
    out: dict = {}
    for bi, name in enumerate(names):
        if wanted and "*" not in wanted and name not in wanted:
            continue
        cols = list(zip(*(fr[bi * 5: bi * 5 + 5] for fr in samples["frames"]))) or [(), (), (), (), ()]
        out[name] = dict(zip(("x", "y", "rotation", "scaleX", "scaleY"), (list(c) for c in cols)))
    return out


def _write_preview(frames, times, fmt: str, out: Path, path: Path, background: str | None) -> None:
    """A JPEG the assistant can look at: the image itself for png / sheet /
    onion, else a contact sheet of the frames (a model cannot watch a GIF or
    a video). At most 1568 px on the long side."""
    from PIL import Image

    if fmt in ("sheet", "onion"):
        img = Image.open(out).convert("RGBA")
    elif fmt == "png" or len(frames) == 1:
        f = frames[0]
        img = _flatten(f, _rgba(background)) if background else Image.alpha_composite(_checker(f.size), f)
    else:
        idx = _pick(len(frames), 12)
        k = min(1.0, 256 / frames[0].width)
        size = (max(1, round(frames[0].width * k)), max(1, round(frames[0].height * k)))
        small = [frames[i].convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA") for i in idx]
        tmp = path.with_suffix(".sheet.png")
        _sheet(small, [times[i] for i in idx], tmp, 6, background, True)
        img = Image.open(tmp).convert("RGBA")
        img.load()
        tmp.unlink()
    k = min(1.0, 1568 / max(img.size))
    if k < 1:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.Resampling.LANCZOS)
    _flatten(img, (38, 40, 46, 255)).convert("RGB").save(path, format="JPEG", quality=85)


def _video(frames_dir: Path, prefix: str, out: Path, fps: float, kind: str, background: str | None,
           frames: list | None = None) -> None:
    ff = _ffmpeg()
    src = frames_dir / f"{prefix}%04d.png"
    if kind == "mp4":
        # No alpha in H.264: flatten, and force even dimensions.
        flat = frames_dir / "flat"
        flat.mkdir(exist_ok=True)
        bg = _rgba(background, (0, 0, 0, 255))
        for i, im in enumerate(frames or []):
            _flatten(im, (bg[0], bg[1], bg[2], 255)).convert("RGB").save(flat / f"{prefix}{i:04d}.png")
        src = flat / f"{prefix}%04d.png"
        codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium",
                 "-movflags", "+faststart", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
    elif kind == "webm":
        codec = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "26",
                 "-auto-alt-ref", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
    else:  # mov
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                 "-vendor", "apl0"]
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{fps:g}", "-i", str(src),
           *codec, str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        raise RuntimeRenderError(f"ffmpeg failed: {p.stderr[-1200:]}")


def render(
    skeleton: str,
    output: str,
    format: str = "gif",
    animation: str | None = None,
    skin: str | None = None,
    time: float | None = None,
    fps: float = 30,
    duration: float | None = None,
    loops: int = 1,
    include_last: bool = False,
    scale: float = 1.0,
    width: int | None = None,
    height: int | None = None,
    padding: float = 16,
    background: str | None = None,
    matte: str | None = None,
    supersample: int = 2,
    warmup: float = 0,
    atlas: str | None = None,
    crop: dict | None = None,
    columns: int = 6,
    label: bool = True,
    max_sheet_frames: int = 24,
    timeout: float = 900,
    runtime_version: str | None = None,
    overlays: list[dict] | None = None,
    loop: bool = True,
    mix: float = 0,
    times: list[float] | None = None,
    debug: bool | dict | None = None,
    track_bones: list[str] | None = None,
    ghosts: int = 8,
    preview: str | None = None,
) -> dict:
    if format not in FORMATS:
        raise RuntimeRenderError(f"format must be one of {', '.join(FORMATS)}")
    if format != "png" and not animation and time is None and format != "frames" and not times:
        raise RuntimeRenderError(f"format {format} needs an animation")
    if format == "sheet" and width is None and height is None and scale == 1.0:
        width = 256  # cell size: a sheet of full-size frames gets huge fast
    if format == "onion" and width is None and height is None and scale == 1.0:
        width = 768
    out = Path(output).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="spine-mcp-") as tmp_s:
        tmp = Path(tmp_s)
        sk, at, how = resolve_inputs(skeleton, atlas, tmp)
        rt = ensure_runtime(runtime_line_for(sk, runtime_version))
        frames_dir = out if format == "frames" else tmp / "frames"
        req = {
            "mode": "render", "runtime_dir": str(rt.dir), "runtime_version": rt.version,
            "skeleton": str(sk), "atlas": str(at), "skin": skin, "animation": animation,
            "time": 0.0 if format == "png" and time is None else time, "times": times,
            "fps": fps, "duration": duration, "loops": loops, "include_last": include_last,
            "scale": scale, "width": width, "height": height, "padding": padding,
            "background": background, "warmup": warmup,
            # Debug lines are 1 px wide: downscaling would wash them out.
            "supersample": 1 if debug else supersample,
            "crop": crop, "out_dir": str(frames_dir), "prefix": "frame_",
            "overlays": overlays or [], "loop": loop, "mix": mix,
            "debug": ({} if debug is True else debug) if debug else None,
            "track": track_bones or None,
        }
        res = _run_worker(req, timeout)
        if not res.get("ok"):
            res.update(skeleton=str(sk), atlas=str(at))
            raise RuntimeRenderError(json.dumps({k: res.get(k) for k in ("stage", "error", "console")}))
        frame_paths = res.pop("frames")
        times = res.pop("times")
        samples = res.pop("samples", None) or {}
        tracks = _tracks(samples, track_bones)
        out.parent.mkdir(parents=True, exist_ok=True)
        frames = _load(frame_paths) if format != "frames" or preview else []
        if format == "frames":
            result_files = frame_paths
        else:
            if format == "png":
                img = frames[0] if not background else _flatten(frames[0], _rgba(background))
                img.save(out)
            elif format == "sheet":
                step = max(1, -(-len(frames) // max_sheet_frames))
                _sheet(frames[::step], times[::step], out, columns, background, label)
            elif format == "onion":
                _onion(frames, times, out, background, ghosts, tracks, res.get("view", {}))
            elif format == "gif":
                _gif(frames, out, fps, background, matte, loop=0)
            elif format == "apng":
                fr = [_flatten(f, _rgba(background)) for f in frames] if background else frames
                fr[0].save(out, format="PNG", save_all=True, append_images=fr[1:],
                           duration=round(1000 / fps), loop=0, disposal=1, blend=0)
            elif format == "webp":
                fr = [_flatten(f, _rgba(background)) for f in frames] if background else frames
                fr[0].save(out, format="WEBP", save_all=True, append_images=fr[1:],
                           duration=round(1000 / fps), loop=0, lossless=True, method=4)
            else:
                _video(Path(frames_dir), "frame_", out, fps, format, background, frames)
            result_files = [str(out)]
        if preview:
            _write_preview(frames, times, format, out, Path(preview), background)
    view = res.get("view", {})
    warnings = []
    if not background and format not in ("mp4",):
        additive = []
        if sk.suffix.lower() == ".json":
            try:
                additive = [x["name"] for x in json.loads(sk.read_text(encoding="utf-8")).get("slots", [])
                            if x.get("blend") == "additive"]
            except (OSError, ValueError, KeyError):
                pass
        if additive:
            warnings.append(
                f"additive slots {additive}: over a transparent background their light is not "
                "added to anything, so glows look missing or weaker than in the game (Spine "
                "behaves the same). Pass background='#rrggbb' (your game's color) to judge them.")
    return {
        **({"warnings": warnings} if warnings else {}),
        "output": str(out) if format != "frames" else str(frames_dir),
        "files": result_files if format == "frames" else result_files,
        "format": format,
        "frames": len(times),
        "fps": fps,
        "duration": round(len(times) / fps, 4) if animation and not req["times"] else 0,
        "size": [view.get("outW"), view.get("outH")],
        "world_bounds": res.get("bounds"),
        "pixels_per_unit": view.get("scale"),
        "supersample": view.get("supersample"),
        "atlas": str(at) if how == "atlas" else None,
        "atlas_source": how,
        "runtime": f"spine-webgl {rt.version}",
        "skeleton_info": res.get("info"),
        **({"times": [round(t, 4) for t in times]} if req["times"] else {}),
        **({"tracks": tracks} if tracks else {}),
        **({"events": samples["events"]} if samples.get("events") else {}),
        **({"preview": str(preview)} if preview else {}),
        **({"console": res["console"]} if res.get("console") else {}),
    }


def sample(
    skeleton: str,
    animation: str | None = None,
    bones: list[str] | None = None,
    fps: float = 30,
    duration: float | None = None,
    loops: int = 1,
    include_last: bool = True,
    warmup: float = 0,
    skin: str | None = None,
    atlas: str | None = None,
    overlays: list[dict] | None = None,
    loop: bool = True,
    mix: float = 0,
    times: list[float] | None = None,
    runtime_version: str | None = None,
    timeout: float = 300,
) -> dict:
    """Bone world transforms over an animation as the official runtime
    computes them (constraints and physics applied), without drawing:
    {times, tracks: {bone: {x, y, rotation, scaleX, scaleY}}, events}."""
    with tempfile.TemporaryDirectory(prefix="spine-mcp-") as tmp:
        sk, at, _ = resolve_inputs(skeleton, atlas, Path(tmp))
        rt = ensure_runtime(runtime_line_for(sk, runtime_version))
        res = _run_worker({
            "mode": "sample", "runtime_dir": str(rt.dir), "runtime_version": rt.version,
            "skeleton": str(sk), "atlas": str(at), "skin": skin, "animation": animation,
            "fps": fps, "duration": duration, "loops": loops, "include_last": include_last,
            "warmup": warmup, "overlays": overlays or [], "loop": loop, "mix": mix,
            "times": times, "track": bones or ["*"],
        }, timeout)
    if not res.get("ok"):
        raise RuntimeRenderError(json.dumps({k: res.get(k) for k in ("stage", "error", "console")}))
    samples = res.get("samples") or {}
    return {
        "animation": animation, "fps": fps, "times": [round(t, 5) for t in res["times"]],
        "tracks": _tracks(samples, bones) or {}, "events": samples.get("events") or [],
        "skeleton_info": res.get("info"), "runtime": f"spine-webgl {rt.version}",
    }
