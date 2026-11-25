"""Quality control of the ART before it is rigged, and safe repairs.

A rig cannot fix a bad cut-out: hard or frayed alpha edges shimmer as soon as
a part rotates, leftover fragments float around the character, a light fringe
from the removed background outlines every piece, and limbs cut edge to edge
open a hole at the joint. These are measurable, so they are measured here:

- `check_image()` / `check_images()`: per-image checks on the pixels;
- `check_joints()`: with a skeleton, bends every joint and looks for the hole
  that opens when the parts do not overlap (no hidden "underpaint");
- `clean_image()`: repairs that never change the drawing or its size (remove
  fragments, antialias hard edges, bleed colours under the transparent rim).

Findings use the same shape as the animation review: {"severity", "code",
"where", "message", "fix"}. They are heuristics that say where to LOOK; the
annotated sheet (`annotate()`) shows it.
"""

from __future__ import annotations

import math
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OPAQUE = 250  # alpha from which a pixel is fully drawn
IMAGE_EXTENSIONS = (".png", ".webp")

# Thresholds (see the checks for what each ratio means).
HARD_EDGE_WARN = 0.45
ROUGH_WARN = 0.30
ROUGH_INFO = 0.15
SPIKES_INFO = 0.18
FRINGE_DELTA = 35.0
SEE_THROUGH_INFO = 0.05
UPSCALE_WARN = 1.25
GAP_WARN = 0.05


def _issue(severity: str, code: str, where: str, message: str, fix: str = "") -> dict:
    out = {"severity": severity, "code": code, "where": where, "message": message}
    if fix:
        out["fix"] = fix
    return out


def _array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.uint8)


def _touching(mask: np.ndarray) -> np.ndarray:
    """True where one of the 4 neighbours is True."""
    out = np.zeros_like(mask)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _erode(mask: np.ndarray, px: int) -> np.ndarray:
    img = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(2 * px + 1))
    return np.asarray(img) > 127


def _perimeter(mask: np.ndarray) -> int:
    return int((mask & _touching(~mask)).sum())


def _smoothed(mask: np.ndarray, radius: float) -> np.ndarray:
    """The mask without the details thinner than ~radius."""
    pad = int(3 * radius) + 1
    wide = np.pad(mask, pad).astype(np.uint8) * 255
    blurred = np.asarray(Image.fromarray(wide).filter(ImageFilter.GaussianBlur(radius))) > 127
    return blurred[pad:-pad, pad:-pad]


def _pool(mask: np.ndarray, f: int) -> np.ndarray:
    """Pixels per f x f cell (so nothing, however small, is lost)."""
    h, w = mask.shape
    H, W = -(-h // f) * f, -(-w // f) * f
    full = np.zeros((H, W), dtype=np.int32)
    full[:h, :w] = mask
    return full.reshape(H // f, f, W // f, f).sum(axis=(1, 3))


def components(mask: np.ndarray) -> tuple[np.ndarray, list[dict], int]:
    """Connected pieces of `mask` (8-connected, on a grid of at most ~384
    cells a side): (label per cell, [{"label", "area" px, "box" px}] largest
    first, cell size)."""
    f = max(1, math.ceil(max(mask.shape) / 384))
    cells = _pool(mask, f)
    filled = cells > 0
    h, w = filled.shape
    labels = np.zeros((h, w), dtype=np.int32)
    grid = filled.tolist()
    lab = labels.tolist()
    comps: list[dict] = []
    for y0 in range(h):
        row = grid[y0]
        for x0 in range(w):
            if not row[x0] or lab[y0][x0]:
                continue
            n = len(comps) + 1
            lab[y0][x0] = n
            queue = deque([(y0, x0)])
            x_min = x_max = x0
            y_min = y_max = y0
            while queue:
                y, x = queue.popleft()
                x_min, x_max, y_min, y_max = min(x_min, x), max(x_max, x), min(y_min, y), max(y_max, y)
                for yy in (y - 1, y, y + 1):
                    if yy < 0 or yy >= h:
                        continue
                    for xx in (x - 1, x, x + 1):
                        if 0 <= xx < w and grid[yy][xx] and not lab[yy][xx]:
                            lab[yy][xx] = n
                            queue.append((yy, xx))
            comps.append({"label": n, "box": [x_min * f, y_min * f, (x_max + 1) * f, (y_max + 1) * f]})
    labels = np.asarray(lab, dtype=np.int32).reshape(h, w)
    if comps:
        areas = np.bincount(labels.ravel(), weights=cells.ravel(), minlength=len(comps) + 1)
        for c in comps:
            c["area"] = int(areas[c["label"]])
    comps.sort(key=lambda c: c["area"], reverse=True)
    return labels, comps, f


def _fragments(alpha: np.ndarray) -> tuple[np.ndarray, list[dict], list[dict], int]:
    """(labels, main pieces, leftover fragments, cell size). A fragment is a
    piece smaller than 3 % of the largest one."""
    labels, comps, f = components(alpha > 32)
    if not comps:
        return labels, [], [], f
    limit = 0.03 * comps[0]["area"]
    return labels, [c for c in comps if c["area"] >= limit], [c for c in comps if c["area"] < limit], f


def check_image(img: Image.Image, name: str = "image") -> dict:
    """Pixel-level review of one part."""
    arr = np.pad(_array(img), ((2, 2), (2, 2), (0, 0)))
    a = arr[..., 3]
    h, w = a.shape[0] - 4, a.shape[1] - 4
    issues: list[dict] = []
    drawn = a >= 128
    area = int(drawn.sum())
    metrics: dict[str, Any] = {"size": [w, h], "area_px": area}
    if area == 0:
        if (a > 0).any():
            # A part that is translucent everywhere (shadow, haze): nothing to cut out.
            metrics["translucent"] = True
        else:
            issues.append(_issue("info", "empty", name, "the image is fully transparent (a placeholder?)"))
        return {"name": name, "metrics": metrics, "issues": issues, "marks": {}}
    marks: dict[str, Any] = {}
    transparent, opaque = a == 0, a >= OPAQUE

    # Hard edges: the transparent rim touches fully opaque pixels directly,
    # with no semi-transparent pixel in between (no antialiasing).
    rim = transparent & _touching(~transparent)
    hard = rim & _touching(opaque)
    hard_ratio = float(hard.sum()) / max(int(rim.sum()), 1)
    metrics["hard_edge"] = round(hard_ratio, 3)
    if hard_ratio > HARD_EDGE_WARN and rim.sum() > 40:
        marks["hard"] = hard[2:-2, 2:-2]
        issues.append(_issue(
            "warning", "hard_edges", name,
            f"{round(100 * hard_ratio)} % of the outline jumps from opaque to transparent with no "
            "antialiasing: stair-stepped edges that shimmer when the part rotates or scales",
            "clean_art (soften) repairs it; at generation ask for a clean antialiased cut-out, "
            "not a thresholded mask"))

    # Frayed outline: a contour much longer than the same shape smoothed, at
    # the scale of a few pixels (fray) and of the part itself (torn spikes).
    diag = math.hypot(w, h)
    fine_shape = _smoothed(drawn, max(2.0, 0.006 * diag))
    coarse_shape = _smoothed(drawn, max(4.0, 0.02 * diag))
    outline = _perimeter(drawn)
    rough = outline / max(_perimeter(fine_shape), 1) - 1
    spikes = outline / max(_perimeter(coarse_shape), 1) - 1
    metrics["edge_roughness"] = round(rough, 3)
    metrics["shape_roughness"] = round(spikes, 3)
    if rough > ROUGH_INFO or spikes > SPIKES_INFO:
        # Clean at the scale of a few pixels but not at the scale of the part:
        # large spikes, which trimming cannot repair.
        torn = rough <= ROUGH_INFO
        diff = (drawn ^ (coarse_shape if torn else fine_shape))[2:-2, 2:-2]
        marks["rough"] = diff
        f = max(8, max(w, h) // 12)
        blocks = _pool(diff, f)
        by, bx = np.unravel_index(int(blocks.argmax()), blocks.shape)
        where = f"{name} (worst around x={bx * f + f // 2}, y={by * f + f // 2})"
        issues.append(_issue(
            "warning" if max(rough, spikes) > ROUGH_WARN else "info", "frayed_edges", where,
            f"the outline is {round(100 * max(rough, spikes))} % longer than its smoothed shape: "
            + ("large spikes and notches, a torn cut-out rather than a drawn shape"
               if torn else "spikes, notches or fray left by the cut-out")
            + " (fine for fur or hair drawn that way)",
            "regenerate the part as a clean closed shape" if torn else
            "clean_art smooth=2 trims thin spikes; regenerate the part if the edge is torn"))

    # Leftover fragments: small pieces detached from the part.
    labels, mains, frags, cell = _fragments(a)
    stray = [c for c in frags if c["area"] >= 6]
    metrics["pieces"] = len(mains)
    metrics["fragments"] = len(stray)
    if stray:
        marks["fragments"] = [[max(0, v - 2) for v in c["box"]] for c in stray[:20]]
        px = sum(c["area"] for c in stray)
        issues.append(_issue(
            "warning", "fragments", name,
            f"{len(stray)} detached fragment(s), {px} px in total (largest {stray[0]['area']} px): "
            "leftovers of the cut-out that will float next to the part",
            "clean_art removes them"))
    if len(mains) > 1:
        issues.append(_issue(
            "info", "several_pieces", name,
            f"{len(mains)} separate pieces in one image: they will move as one block; split them "
            "into one image each if they must move independently"))

    # See-through patches inside the shape.
    inside = _erode(a > 0, 4)
    see = inside & (a < 200)
    see_ratio = float(see.sum()) / area
    metrics["see_through"] = round(see_ratio, 3)
    if see_ratio > SEE_THROUGH_INFO:
        issues.append(_issue(
            "info", "see_through", name,
            f"{round(100 * see_ratio)} % of the inside is semi-transparent: right for smoke, glow "
            "or a shadow, a defect (what is behind shows through) for a solid part"))

    # Light fringe: the outermost opaque pixels much brighter than those just inside.
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    in2, in6 = _erode(opaque, 2), _erode(opaque, 6)
    edge, inner = opaque & ~in2, in2 & ~in6
    if edge.sum() > 60 and inner.sum() > 60:
        delta = float(lum[edge].mean() - lum[inner].mean())
        metrics["edge_lightness"] = round(delta, 1)
        if delta > FRINGE_DELTA and lum[edge].mean() > 140:
            marks["fringe"] = edge[2:-2, 2:-2]
            issues.append(_issue(
                "warning", "light_fringe", name,
                f"the outline is {round(delta)} levels lighter than the art just inside: a halo "
                "of the removed background around the part",
                "regenerate on a transparent background, or erode the mask by 1-2 px"))

    # Cut by the canvas: a straight edge unless another part hides it.
    sides = {"top": drawn[2, 2:-2], "bottom": drawn[-3, 2:-2], "left": drawn[2:-2, 2], "right": drawn[2:-2, -3]}
    cut = {k: int(v.sum()) for k, v in sides.items() if v.sum() >= max(8, 0.1 * v.size)}
    if cut:
        metrics["cut_by_border"] = cut
        issues.append(_issue(
            "info", "cut_by_border", name,
            "the art reaches the image border (" + ", ".join(f"{k}: {v} px" for k, v in cut.items())
            + "): a straight cut there, visible unless another part covers it"))

    # Sharpness of the lines inside, to compare parts with each other.
    core = _erode(opaque, 3)[1:, 1:]
    if core.sum() > 200:
        grad = np.maximum(np.abs(np.diff(lum, axis=0))[:, 1:], np.abs(np.diff(lum, axis=1))[1:, :])
        metrics["sharpness"] = round(float(np.percentile(grad[core], 99)), 1)
    return {"name": name, "metrics": metrics, "issues": issues, "marks": marks}


def check_images(images: dict[str, Image.Image]) -> list[dict]:
    """Review a set of parts, including how they compare with each other."""
    reports = [check_image(img, name) for name, img in images.items()]
    sharp = sorted(r["metrics"]["sharpness"] for r in reports if "sharpness" in r["metrics"])
    if len(sharp) >= 4:
        median = sharp[len(sharp) // 2]
        for r in reports:
            s = r["metrics"].get("sharpness")
            if s is not None and median > 20 and 8 < s < 0.5 * median:
                r["issues"].append(_issue(
                    "info", "soft_art", r["name"],
                    f"lines about {round(median / max(s, 1), 1)}x softer than the other parts "
                    "(enlarged or generated at a lower resolution?): it will look blurry next to them",
                    "regenerate it at the same resolution as the rest"))
    return reports


# ------------------------------------------------------------ skeleton
def check_attachments(data: dict, images: dict[str, Image.Image]) -> list[dict]:
    """Images drawn larger than their pixels, or stretched, by the skeleton."""
    issues: list[dict] = []
    for skin in data.get("skins") or []:
        for slot, atts in (skin.get("attachments") or {}).items():
            for name, att in atts.items():
                if att.get("type", "region") not in ("region", "mesh") or not att.get("width"):
                    continue
                path = att.get("path") or att.get("name") or name
                img = images.get(path)
                if img is None:
                    continue
                sx = float(att["width"]) * abs(float(att.get("scaleX", 1))) / img.width
                sy = float(att["height"]) * abs(float(att.get("scaleY", 1))) / img.height
                where = f"{slot}/{name}"
                if max(sx, sy) > UPSCALE_WARN:
                    issues.append(_issue(
                        "warning", "upscaled", where,
                        f"drawn {round(max(sx, sy), 2)}x larger than the image ({img.width}x{img.height} px): blurry",
                        "generate the part at least at its display size (2x is better)"))
                elif abs(sx / sy - 1) > 0.04:
                    issues.append(_issue(
                        "warning", "stretched", where,
                        f"the image is stretched ({round(sx, 2)} x {round(sy, 2)}): attachment size "
                        f"{att['width']}x{att['height']} does not match the image {img.width}x{img.height}",
                        "update_attachment with the image's own width / height"))
    return issues


def _bridged(data: dict, bone_index: dict[str, int], att: dict, inside: set[str]) -> bool:
    """True when a mesh is weighted to bones on both sides of the joint."""
    verts = att.get("vertices") or []
    if att.get("type") != "mesh" or len(verts) <= len(att.get("uvs") or []):
        return False
    names = [b["name"] for b in data["bones"]]
    used: set[str] = set()
    i = 0
    while i < len(verts):
        n = int(verts[i])
        for k in range(n):
            used.add(names[int(verts[i + 1 + 4 * k])])
        i += 1 + 4 * n
    return bool(used & inside) and bool(used - inside)


def check_joints(data: dict, source, skin: str | None = None, angle: float = 25.0) -> list[dict]:
    """Bend every joint by +/- `angle` and measure the hole that opens.

    For each bone that carries art (itself or below it) attached to a parent
    that carries art: the part is rotated around its pivot; pixels it covered
    next to the pivot that neither it nor the parent's art cover any more are
    a gap: the parts were cut edge to edge, with nothing drawn underneath.
    Joints bridged by a weighted mesh are skipped (the mesh bends instead)."""
    from . import document as doc
    from .pose import Pose
    from .preview import collect_items, draw_item

    setup = Pose(data)
    items = collect_items(data, setup, source, skin)
    items = [it for it in items if it.img is not None]
    if not items:
        return []
    xs = [p[0] for it in items for p in it.points]
    ys = [p[1] for it in items for p in it.points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    s = min(1.0, 720 / span)
    margin = 0.35 * span
    x0, y1 = min(xs) - margin, max(ys) + margin
    W, H = int((max(xs) - min(xs) + 2 * margin) * s) + 2, int((max(ys) - min(ys) + 2 * margin) * s) + 2

    def to_px(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * s, (y1 - y) * s

    def coverage(draw: list) -> np.ndarray:
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for it in draw:
            draw_item(canvas, it, to_px)
        return np.asarray(canvas.getchannel("A")) >= 128

    by_bone: dict[str, list] = {}
    for it in items:
        by_bone.setdefault(it.bone, []).append(it)
    parent = {b["name"]: b.get("parent") for b in data["bones"]}
    index = {b["name"]: i for i, b in enumerate(data["bones"])}
    yy, xx = np.mgrid[0:H, 0:W]
    found: list[dict] = []
    for bone in (b["name"] for b in data["bones"]):
        partner_bone = parent.get(bone)
        while partner_bone is not None and partner_bone not in by_bone:
            partner_bone = parent.get(partner_bone)
        if partner_bone is None or parent.get(partner_bone) is None:
            continue  # hangs off the root: a separate object, not a joint
        inside = {bone, *doc.descendants(data, bone)}
        part = [it for it in items if it.bone in inside]
        partner = by_bone[partner_bone]
        if not part or bone not in by_bone:
            continue
        if any(_bridged(data, index, it.att, inside) for it in part + partner):
            continue
        before = coverage(part)
        px, py = to_px(setup.bones[bone].worldX, setup.bones[bone].worldY)
        ys_, xs_ = np.nonzero(before)
        if not len(xs_):
            continue
        reach = 0.15 * math.hypot(xs_.max() - xs_.min(), ys_.max() - ys_.min())
        near = (xx - px) ** 2 + (yy - py) ** 2 <= reach**2
        thickness = 2 * math.sqrt(float((before & near).sum()) / math.pi)
        radius = min(max(0.6 * thickness, 5.0), max(reach, 5.0))
        zone = (xx - px) ** 2 + (yy - py) ** 2 <= radius**2
        if (before & zone).sum() < 0.15 * zone.sum():
            continue  # the pivot is not on this part's art: nothing to judge
        other = coverage(partner)
        around = (xx - px) ** 2 + (yy - py) ** 2 <= (2 * radius) ** 2
        if not (other & around).any():
            continue  # the parent's art is nowhere near: two separate objects, not a joint
        worst = 0.0
        for turn in (angle, -angle):
            bent = {**data, "bones": [
                {**b, "rotation": float(b.get("rotation", 0)) + turn} if b["name"] == bone else b
                for b in data["bones"]]}
            posed = collect_items(bent, Pose(bent), source, skin)
            after = coverage([it for it in posed if it.bone in inside and it.img is not None])
            worst = max(worst, float((before & zone & ~other & ~after).sum()) / max(int(zone.sum()), 1))
        overlap = float((before & other & zone).sum()) / max(int(zone.sum()), 1)
        if worst > GAP_WARN:
            found.append({
                "bone": bone, "parent_art": partner_bone, "gap": round(worst, 3), "overlap": round(overlap, 3),
                "pivot_px": [round(px), round(py)], "radius_px": round(radius),
                **_issue(
                    "warning", "joint_gap", f"{partner_bone} > {bone}",
                    f"bending {bone!r} by {round(angle)} deg opens a hole at the joint ({round(100 * worst)} % "
                    f"of the joint area; the two parts overlap on {round(100 * overlap)} % of it)",
                    f"redraw {bone!r} with a rounded end that continues ~{max(3, round(radius / s))} units "
                    f"under {partner_bone!r} (hidden underpaint), or bridge the joint with a weighted mesh"),
            })
    return found


def joints_overview(data: dict, source, joints: list[dict], skin: str | None = None) -> Image.Image:
    """The setup pose with a circle on every joint that opens."""
    from .pose import Pose
    from .preview import collect_items, draw_item

    setup = Pose(data)
    items = [it for it in collect_items(data, setup, source, skin) if it.img is not None]
    xs = [p[0] for it in items for p in it.points]
    ys = [p[1] for it in items for p in it.points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    s = min(1.0, 720 / span)
    margin = 0.35 * span
    x0, y1 = min(xs) - margin, max(ys) + margin
    W, H = int((max(xs) - min(xs) + 2 * margin) * s) + 2, int((max(ys) - min(ys) + 2 * margin) * s) + 2
    canvas = Image.new("RGBA", (W, H), (58, 58, 68, 255))
    for it in items:
        draw_item(canvas, it, lambda x, y: ((x - x0) * s, (y1 - y) * s))
    d = ImageDraw.Draw(canvas)
    for j in joints:
        (px, py), r = j["pivot_px"], max(j["radius_px"], 8)
        d.ellipse([px - r, py - r, px + r, py + r], outline=(255, 40, 120, 255), width=3)
        label = f"{j['bone']} {round(100 * j['gap'])}%"
        box = d.textbbox((px + r + 4, py - 6), label)
        d.rectangle([box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2], fill=(20, 20, 24, 255))
        d.text((px + r + 4, py - 6), label, fill=(255, 255, 255, 255))
    keep = (margin - 0.06 * span) * s
    return canvas.crop((int(keep), int(keep), int(W - keep), int(H - keep)))


# ------------------------------------------------------------- repairs
def bleed_colors(arr: np.ndarray, steps: int = 8) -> np.ndarray:
    """Spread the art's colours under the fully transparent pixels around it
    (alpha untouched). Without it those pixels are black or white, and any
    engine that filters or resizes the texture with straight alpha pulls that
    colour into the outline."""
    alpha = arr[..., 3]
    known = alpha > 0
    if not known.any() or known.all():
        return arr
    rgb = arr[..., :3].astype(np.float32)
    rgb[~known] = 0
    for _ in range(steps):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(known.shape, dtype=np.float32)
        k = known.astype(np.float32)
        src = rgb * k[..., None]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not dy and not dx:
                    continue
                ys = slice(max(dy, 0), known.shape[0] + min(dy, 0))
                yd = slice(max(-dy, 0), known.shape[0] + min(-dy, 0))
                xs = slice(max(dx, 0), known.shape[1] + min(dx, 0))
                xd = slice(max(-dx, 0), known.shape[1] + min(-dx, 0))
                acc[yd, xd] += src[ys, xs]
                cnt[yd, xd] += k[ys, xs]
        new = ~known & (cnt > 0)
        if not new.any():
            break
        rgb[new] = acc[new] / cnt[new][:, None]
        known = known | new
    out = arr.copy()
    out[..., :3] = np.where((alpha == 0)[..., None], np.clip(rgb + 0.5, 0, 255).astype(np.uint8), arr[..., :3])
    return out


def clean_image(
    img: Image.Image, fragments: bool = True, soften: float | None = None, smooth: float = 0.0,
    bleed: int = 8,
) -> tuple[Image.Image, dict]:
    """Repairs that keep the drawing and its size: (image, what was done).

    fragments: erase detached leftovers. soften: antialias the outline by this
    radius in px, inwards only (None = 0.8 when the edges are hard, else
    nothing). smooth: trim spikes thinner than this many px (0 = off; it also
    trims drawn fur or whiskers). bleed: px of colour spread under the
    transparent rim."""
    arr = _array(img).copy()
    done: dict[str, Any] = {}
    if fragments:
        labels, _, frags, cell = _fragments(arr[..., 3])
        stray = [c for c in frags if c["area"] >= 1]
        if stray:
            kill = np.isin(labels, [c["label"] for c in stray])
            kill = np.repeat(np.repeat(kill, cell, axis=0), cell, axis=1)[: arr.shape[0], : arr.shape[1]]
            arr[kill, 3] = 0
            done["fragments_removed"] = {"count": len(stray), "px": sum(c["area"] for c in stray)}
    alpha = Image.fromarray(arr[..., 3])
    if smooth > 0:
        mask = alpha.point(lambda v: 255 if v >= 128 else 0)
        blurred = np.asarray(mask.filter(ImageFilter.GaussianBlur(smooth)), dtype=np.float32)
        limit = np.clip((blurred - 96) * 4, 0, 255).astype(np.uint8)
        arr[..., 3] = np.minimum(arr[..., 3], limit)
        alpha = Image.fromarray(arr[..., 3])
        done["smoothed_px"] = smooth
    if soften is None:
        hard = check_image(Image.fromarray(arr), "x")["metrics"].get("hard_edge", 0)
        soften = 0.8 if hard > HARD_EDGE_WARN else 0.0
    if soften > 0:
        blurred = np.asarray(alpha.filter(ImageFilter.GaussianBlur(soften)))
        arr[..., 3] = np.minimum(arr[..., 3], blurred)
        done["softened_px"] = soften
    if bleed > 0:
        arr = bleed_colors(arr, bleed)
        done["bleed_px"] = bleed
    return Image.fromarray(arr), done


# ------------------------------------------------------------ pictures
def annotate(images: dict[str, Image.Image], reports: list[dict], limit: int = 12, cell: int = 320) -> Image.Image | None:
    """Contact sheet of the parts with findings, the defects painted on:
    red = hard outline, magenta = frayed outline, yellow boxes = fragments,
    cyan = light fringe."""
    order = {"warning": 0, "info": 1}
    flagged = [r for r in reports if r["issues"]]
    flagged.sort(key=lambda r: (min(order.get(i["severity"], 2) for i in r["issues"]), -len(r["issues"])))
    flagged = flagged[:limit]
    if not flagged:
        return None
    cols = min(4, len(flagged))
    rows = -(-len(flagged) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), (38, 40, 46))
    for n, r in enumerate(flagged):
        img = images[r["name"]].convert("RGBA")
        over = np.zeros((img.height, img.width, 4), dtype=np.uint8)
        for key, color in (("rough", (255, 0, 255, 255)), ("fringe", (0, 229, 255, 255)), ("hard", (255, 40, 40, 255))):
            m = r["marks"].get(key)
            if m is not None:
                over[m[: img.height, : img.width]] = color
        tile = Image.new("RGBA", img.size, (120, 150, 120, 255))
        tile.alpha_composite(img)
        thick = Image.fromarray(over).filter(ImageFilter.MaxFilter(3 if max(img.size) < 600 else 5))
        tile.alpha_composite(thick)
        d = ImageDraw.Draw(tile)
        for box in r["marks"].get("fragments") or []:
            d.rectangle([box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3], outline=(255, 230, 0, 255), width=max(2, max(img.size) // 200))
        k = min((cell - 8) / tile.width, (cell - 8) / tile.height)
        tile = tile.resize((max(1, round(tile.width * k)), max(1, round(tile.height * k))),
                           Image.Resampling.LANCZOS if k < 1 else Image.Resampling.NEAREST)
        ox, oy = (n % cols) * cell, (n // cols) * (cell + 30)
        sheet.paste(tile.convert("RGB"), (ox + (cell - tile.width) // 2, oy + 30 + (cell - tile.height) // 2))
        codes = ", ".join(sorted({i["code"] for i in r["issues"]}))
        ImageDraw.Draw(sheet).text((ox + 4, oy + 3), r["name"][:44], fill=(255, 255, 255))
        ImageDraw.Draw(sheet).text((ox + 4, oy + 15), codes[:52], fill=(255, 190, 80))
    return sheet


def load_images(path: str | Path, names: list[str] | None = None) -> dict[str, Image.Image]:
    """Images of a folder (recursive; names = paths without extension), of a
    single file, or the regions of a .atlas."""
    p = Path(path).expanduser().resolve()
    out: dict[str, Image.Image] = {}
    if p.suffix.lower() == ".atlas":
        from ..atlas.reader import read_atlas, region_image

        atlas = read_atlas(p)
        pages: dict = {}
        for r in atlas.regions:
            out[r.name] = region_image(atlas, r, pages)
    elif p.is_dir():
        for f in sorted(p.rglob("*")):
            if f.suffix.lower() in IMAGE_EXTENSIONS and f.is_file():
                out[f.relative_to(p).with_suffix("").as_posix()] = Image.open(f).convert("RGBA")
    elif p.is_file():
        out[p.stem] = Image.open(p).convert("RGBA")
    else:
        raise ValueError(f"no image, folder or .atlas at {p}")
    if names:
        missing = [n for n in names if n not in out]
        if missing:
            raise ValueError(f"images not found: {missing}")
        out = {n: out[n] for n in names}
    if not out:
        raise ValueError(f"no PNG / WebP image in {p}")
    return out
