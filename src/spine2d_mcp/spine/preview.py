"""Headless PNG preview of a skeleton pose (setup pose or an animation frame).

Pure Python (Pillow), no Spine install needed, so an agent can look at what
it built. Renders region and mesh attachments (weighted or not, with deform
keys), slot colors/alpha, draw order and draw order folders, plus optional
bone overlays. Images come from the skeleton's images folder (`<path>.png`)
or from a texture atlas. Constraints and clipping are not simulated; for
pixel-exact output use the Spine CLI image/video export (`spine_export`).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..atlas.reader import Atlas, read_atlas, region_image
from .pose import Pose


class ImageSource:
    def __init__(self, images_dir: Path | None = None, atlas: Atlas | None = None):
        self.images_dir = images_dir
        self.atlas = atlas
        self._cache: dict[str, Image.Image | None] = {}
        self._pages: dict = {}

    def get(self, path: str) -> Image.Image | None:
        if path in self._cache:
            return self._cache[path]
        img = None
        if self.atlas is not None:
            r = self.atlas.find(path)
            if r is not None:
                img = region_image(self.atlas, r, self._pages)
        if img is None and self.images_dir is not None:
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                p = self.images_dir / f"{path}{ext}"
                if p.exists():
                    img = Image.open(p).convert("RGBA")
                    break
        self._cache[path] = img
        return img


def _resolve_images(skeleton_path: Path, data: dict, images_dir: str | None) -> Path | None:
    if images_dir:
        return Path(images_dir)
    rel = (data.get("skeleton") or {}).get("images")
    if rel:
        p = Path(rel)
        return p if p.is_absolute() else (skeleton_path.parent / p).resolve()
    guess = skeleton_path.parent / "images"
    return guess if guess.exists() else None


def render(
    data: dict,
    out_path: str | Path,
    skeleton_path: str | Path | None = None,
    animation: str | None = None,
    time: float = 0.0,
    skin: str | None = None,
    images_dir: str | None = None,
    atlas_path: str | None = None,
    size: tuple[int, int] | None = None,
    padding: int = 20,
    background: str | None = "#2b2b2b",
    show_bones: bool = False,
    scale: float = 1.0,
) -> dict:
    skeleton_path = Path(skeleton_path) if skeleton_path else Path(out_path)
    atlas = read_atlas(atlas_path) if atlas_path else None
    if atlas is None:
        guess = skeleton_path.with_suffix(".atlas")
        if guess.exists() and not images_dir:
            atlas = read_atlas(guess)
    src = ImageSource(_resolve_images(skeleton_path, data, images_dir), atlas)
    pose = Pose(data, animation=animation, time=time)

    skins = {s["name"]: s for s in data.get("skins") or []}
    active = [skins.get("default")] + ([skins.get(skin)] if skin and skin != "default" else [])
    active = [s for s in active if s]

    items: list[tuple[str, Image.Image | None, Any, list[float]]] = []
    missing: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    for slot_name in pose.draw_order:
        st = pose.slots[slot_name]
        if not st.visible or not st.attachment:
            continue
        att, att_skin = None, None
        for s in reversed(active):
            a = ((s.get("attachments") or {}).get(slot_name) or {}).get(st.attachment)
            if a is not None:
                att, att_skin = a, s["name"]
                break
        if att is None:
            continue
        atype = att.get("type", "region")
        if atype == "linkedmesh":
            src_skin = skins.get(att.get("skin") or "default") or {}
            source = ((src_skin.get("attachments") or {}).get(att.get("slot") or slot_name) or {}).get(att.get("source"))
            if source is None:
                continue
            geom = dict(source)
            geom["path"] = att.get("path") or att.get("name") or st.attachment
            att = geom
            atype = "mesh"
        bone = pose.bones[st.bone]
        path = att.get("path") or att.get("name") or st.attachment
        seq = att.get("sequence")
        if seq:
            idx = seq.get("setup", 0) + seq.get("start", 1)
            digits = seq.get("digits", 0)
            path = f"{path}{str(idx).zfill(digits)}"
        img = src.get(path)
        if img is None:
            missing.append(path)
        color = [a * b for a, b in zip(st.color, _att_color(att))]
        if atype == "region":
            quad = _region_quad(att, bone)
            xs += [p[0] for p in quad]
            ys += [p[1] for p in quad]
            items.append(("region", img, (quad, att), color))
        elif atype == "mesh":
            verts = _mesh_world(att, pose, bone, att_skin, slot_name, st.attachment)
            xs += [p[0] for p in verts]
            ys += [p[1] for p in verts]
            items.append(("mesh", img, (verts, att), color))
    for bn in pose.bones.values():
        xs += [bn.worldX, bn.tip[0]]
        ys += [bn.worldY, bn.tip[1]]
    if not xs:
        xs, ys = [0, 1], [0, 1]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    if size:
        W, H = size
        s = min((W - 2 * padding) / max(maxx - minx, 1), (H - 2 * padding) / max(maxy - miny, 1))
    else:
        s = scale
        W = int(math.ceil((maxx - minx) * s)) + 2 * padding
        H = int(math.ceil((maxy - miny) * s)) + 2 * padding
    W, H = max(W, 8), max(H, 8)
    ox, oy = padding - minx * s, padding + maxy * s

    def to_px(x: float, y: float) -> tuple[float, float]:
        return ox + x * s, oy - y * s

    bg = _parse_bg(background)
    canvas = Image.new("RGBA", (W, H), bg)
    for kind, img, payload, color in items:
        if img is None:
            continue
        tinted = _tint(img, color)
        if kind == "region":
            quad, att = payload
            _draw_region(canvas, tinted, [to_px(*p) for p in quad])
        else:
            verts, att = payload
            _draw_mesh(canvas, tinted, [to_px(*p) for p in verts], att)
    if show_bones:
        d = ImageDraw.Draw(canvas)
        for bn in pose.bones.values():
            a, b = to_px(bn.worldX, bn.worldY), to_px(*bn.tip)
            if bn.length > 0:
                d.line([a, b], fill=(255, 200, 0, 255), width=2)
            d.ellipse([a[0] - 3, a[1] - 3, a[0] + 3, a[1] + 3], outline=(255, 80, 0, 255), width=2)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return {
        "image": str(out_path),
        "size": [W, H],
        "animation": animation,
        "time": time,
        "missing_images": sorted(set(missing)),
        "note": "constraints (IK, transform, path, physics, sliders) and clipping are not simulated in this preview",
    }


def render_sheet(
    data: dict,
    out_path: str | Path,
    animation: str,
    frames: int = 8,
    columns: int = 4,
    cell: tuple[int, int] = (256, 256),
    **kwargs: Any,
) -> dict:
    """Contact sheet of `frames` evenly spaced frames of an animation."""
    from .animation import animation_duration

    anim = (data.get("animations") or {}).get(animation)
    if anim is None:
        raise ValueError(f"animation {animation!r} not found")
    dur = animation_duration(anim)
    tmp_dir = Path(out_path).with_suffix("")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    rows = math.ceil(frames / columns)
    sheet = Image.new("RGBA", (cell[0] * columns, cell[1] * rows), _parse_bg(kwargs.get("background", "#2b2b2b")))
    times = []
    missing: set[str] = set()
    for i in range(frames):
        t = dur * i / frames if dur else 0.0
        times.append(round(t, 4))
        res = render(data, tmp_dir / f"frame_{i:03d}.png", animation=animation, time=t, size=cell, **kwargs)
        missing |= set(res["missing_images"])
        frame = Image.open(res["image"])
        sheet.paste(frame, ((i % columns) * cell[0], (i // columns) * cell[1]))
        d = ImageDraw.Draw(sheet)
        d.text(((i % columns) * cell[0] + 4, (i // columns) * cell[1] + 4), f"t={t:.2f}", fill=(255, 255, 255, 255))
    sheet.save(out_path)
    for p in tmp_dir.glob("frame_*.png"):
        p.unlink()
    try:
        tmp_dir.rmdir()
    except OSError:
        pass
    return {"image": str(out_path), "frames": frames, "times": times, "duration": dur,
            "missing_images": sorted(missing)}


def render_gif(
    data: dict, out_path: str | Path, animation: str, fps: int = 15,
    size: tuple[int, int] = (320, 320), loops: int = 0, **kwargs: Any,
) -> dict:
    from .animation import animation_duration

    anim = (data.get("animations") or {}).get(animation)
    if anim is None:
        raise ValueError(f"animation {animation!r} not found")
    dur = animation_duration(anim) or 1.0 / fps
    n = max(1, int(round(dur * fps)))
    tmp = Path(out_path).with_suffix(".frames")
    tmp.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        res = render(data, tmp / f"f{i:04d}.png", animation=animation, time=i / fps, size=size, **kwargs)
        frames.append(Image.open(res["image"]).convert("RGBA"))
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=int(1000 / fps),
                   loop=loops, disposal=2)
    for p in tmp.glob("*.png"):
        p.unlink()
    try:
        tmp.rmdir()
    except OSError:
        pass
    return {"image": str(out_path), "frames": n, "fps": fps, "duration": dur}


# -------------------------------------------------------------- geometry
def _att_color(att: dict) -> list[float]:
    c = att.get("color")
    if not c:
        return [1.0, 1.0, 1.0, 1.0]
    return [int(c[i : i + 2], 16) / 255.0 for i in range(0, 8, 2)]


def _region_quad(att: dict, bone) -> list[tuple[float, float]]:
    w, h = float(att["width"]), float(att["height"])
    sx, sy = float(att.get("scaleX", 1)), float(att.get("scaleY", 1))
    r = math.radians(float(att.get("rotation", 0)))
    cx, cy = float(att.get("x", 0)), float(att.get("y", 0))
    cos, sin = math.cos(r), math.sin(r)
    out = []
    # top-left, top-right, bottom-right, bottom-left (image order)
    for lx, ly in ((-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2), (-w / 2, -h / 2)):
        lx, ly = lx * sx, ly * sy
        x = cx + lx * cos - ly * sin
        y = cy + lx * sin + ly * cos
        out.append(bone.local_to_world(x, y))
    return out


def _mesh_world(att: dict, pose: Pose, bone, skin: str, slot: str, name: str) -> list[tuple[float, float]]:
    verts = list(att.get("vertices") or [])
    n = len(att.get("uvs") or []) // 2
    weighted = len(verts) != n * 2
    influences = _influence_count(verts) if weighted else 0
    # Deform offsets: per vertex (unweighted) or per bone influence (weighted),
    # matching DeformTimeline's deformLength in the 4.3 reader.
    length = influences * 2 if weighted else n * 2
    deform = None
    db = pose.deform_for(skin or "default", slot, name)
    if db is not None:
        k1, k2, a = db
        deform = _deform_offsets(k1, length)
        if k2 is not None and a:
            d2 = _deform_offsets(k2, length)
            deform = [x + (y - x) * a for x, y in zip(deform, d2)]
    out = []
    if not weighted:
        for i in range(n):
            x, y = verts[i * 2], verts[i * 2 + 1]
            if deform:
                x, y = x + deform[i * 2], y + deform[i * 2 + 1]
            out.append(bone.local_to_world(x, y))
        return out
    names = list(pose.bones)
    i = fi = 0
    while i < len(verts):
        bc = int(verts[i])
        i += 1
        wx = wy = 0.0
        for _ in range(bc):
            bn = pose.bones[names[int(verts[i])]]
            x, y, w = verts[i + 1], verts[i + 2], verts[i + 3]
            if deform:
                x, y = x + deform[fi * 2], y + deform[fi * 2 + 1]
            px, py = bn.local_to_world(x, y)
            wx += px * w
            wy += py * w
            i += 4
            fi += 1
        out.append((wx, wy))
    return out


def _influence_count(verts: list) -> int:
    i = count = 0
    while i < len(verts):
        bc = int(verts[i])
        count += bc
        i += 1 + bc * 4
    return count


def _deform_offsets(key: dict, length: int) -> list[float]:
    out = [0.0] * length
    vals = key.get("vertices")
    if vals:
        start = int(key.get("offset", 0))
        for j, v in enumerate(vals):
            if start + j < length:
                out[start + j] = float(v)
    return out


def _tint(img: Image.Image, color: list[float]) -> Image.Image:
    if all(abs(c - 1.0) < 1e-6 for c in color):
        return img
    r, g, b, a = img.split()
    r = r.point(lambda v: int(v * color[0]))
    g = g.point(lambda v: int(v * color[1]))
    b = b.point(lambda v: int(v * color[2]))
    a = a.point(lambda v: int(v * color[3]))
    return Image.merge("RGBA", (r, g, b, a))


def _affine_from_tri(src, dst):
    """Coefficients mapping dst pixel -> src pixel (PIL AFFINE expects the
    inverse mapping)."""
    (x0, y0), (x1, y1), (x2, y2) = dst
    (u0, v0), (u1, v1), (u2, v2) = src
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        return None
    a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det
    b = ((u2 - u0) * (x1 - x0) - (u1 - u0) * (x2 - x0)) / det
    c = u0 - a * x0 - b * y0
    d = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det
    e = ((v2 - v0) * (x1 - x0) - (v1 - v0) * (x2 - x0)) / det
    f = v0 - d * x0 - e * y0
    return (a, b, c, d, e, f)


def _draw_tri(canvas: Image.Image, img: Image.Image, src, dst) -> None:
    coeffs = _affine_from_tri(src, dst)
    if coeffs is None:
        return
    minx = max(int(math.floor(min(p[0] for p in dst))) - 1, 0)
    miny = max(int(math.floor(min(p[1] for p in dst))) - 1, 0)
    maxx = min(int(math.ceil(max(p[0] for p in dst))) + 1, canvas.width)
    maxy = min(int(math.ceil(max(p[1] for p in dst))) + 1, canvas.height)
    if maxx <= minx or maxy <= miny:
        return
    a, b, c, d, e, f = coeffs
    # Shift so the transform is relative to the patch origin.
    c2 = c + a * minx + b * miny
    f2 = f + d * minx + e * miny
    patch = img.transform((maxx - minx, maxy - miny), Image.Transform.AFFINE,
                          (a, b, c2, d, e, f2), resample=Image.Resampling.BILINEAR)
    mask = Image.new("L", patch.size, 0)
    ImageDraw.Draw(mask).polygon([(x - minx, y - miny) for x, y in dst], fill=255)
    alpha = Image.composite(patch.getchannel("A"), Image.new("L", patch.size, 0), mask)
    patch.putalpha(alpha)
    canvas.alpha_composite(patch, (minx, miny))


def _draw_region(canvas: Image.Image, img: Image.Image, quad) -> None:
    w, h = img.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    _draw_tri(canvas, img, [src[0], src[1], src[2]], [quad[0], quad[1], quad[2]])
    _draw_tri(canvas, img, [src[0], src[2], src[3]], [quad[0], quad[2], quad[3]])


def _draw_mesh(canvas: Image.Image, img: Image.Image, verts, att: dict) -> None:
    w, h = img.size
    uvs = att.get("uvs") or []
    tris = att.get("triangles") or []
    src = [(uvs[i] * w, uvs[i + 1] * h) for i in range(0, len(uvs), 2)]
    for t in range(0, len(tris), 3):
        i0, i1, i2 = tris[t : t + 3]
        _draw_tri(canvas, img, [src[i0], src[i1], src[i2]], [verts[i0], verts[i1], verts[i2]])


def _parse_bg(bg: str | None) -> tuple[int, int, int, int]:
    if not bg:
        return (0, 0, 0, 0)
    c = bg.lstrip("#")
    if len(c) == 6:
        c += "ff"
    return tuple(int(c[i : i + 2], 16) for i in range(0, 8, 2))  # type: ignore[return-value]
