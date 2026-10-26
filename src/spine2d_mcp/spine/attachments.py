"""Builders for every 4.3 attachment type, plus mesh helpers.

All builders return the attachment dict (only non-default fields), ready for
`document.set_attachment`. Coordinates are in the slot bone's local space
(Spine y-up), exactly as in exported JSON.

Mesh helpers:
- `grid_mesh`: a rows x cols grid over a w x h image (deformable "free form"
  mesh with a proper hull), the common starting point for squash/stretch,
  breathing, cloth and face meshes.
- `polygon_mesh`: triangulates an outline (ear clipping) so a mesh can follow
  the silhouette of a part, also used for clipping/bounding boxes.
- `auto_weights`: binds mesh vertices to several bones (inverse-distance to
  the bone segments, max 4 influences, normalized), producing Spine's
  weighted vertex layout.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from . import format as fmt


class AttachmentError(ValueError):
    pass


def _r(v: float) -> float | int:
    f = round(float(v), 4)
    if f == 0:
        return 0
    return int(f) if f.is_integer() else f


def _sequence(count: int | None, start: int = 1, digits: int = 0, setup: int = 0) -> dict | None:
    if not count:
        return None
    seq: dict[str, Any] = {"count": int(count)}
    if start != 1:
        seq["start"] = int(start)
    if digits:
        seq["digits"] = int(digits)
    if setup:
        seq["setup"] = int(setup)
    return seq


def _common(att: dict, name: str | None, path: str | None, color: str | None) -> dict:
    if name:
        att["name"] = name
    if path:
        att["path"] = path
    if color and color.lower() != "ffffffff":
        att["color"] = color
    return att


def region(
    width: float,
    height: float,
    x: float = 0.0,
    y: float = 0.0,
    rotation: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    path: str | None = None,
    name: str | None = None,
    color: str | None = None,
    sequence_count: int | None = None,
    sequence_start: int = 1,
    sequence_digits: int = 0,
    sequence_setup: int = 0,
) -> dict:
    if width <= 0 or height <= 0:
        raise AttachmentError("region width/height must be > 0")
    att: dict[str, Any] = {}
    _common(att, name, path, color)
    for k, v, d in (
        ("x", x, 0), ("y", y, 0), ("scaleX", scale_x, 1), ("scaleY", scale_y, 1),
        ("rotation", rotation, 0),
    ):
        if v != d:
            att[k] = _r(v)
    att["width"] = _r(width)
    att["height"] = _r(height)
    seq = _sequence(sequence_count, sequence_start, sequence_digits, sequence_setup)
    if seq:
        att["sequence"] = seq
    return att


def mesh(
    uvs: Sequence[float],
    triangles: Sequence[int],
    vertices: Sequence[float],
    hull: int | None = None,
    edges: Sequence[int] | None = None,
    width: float | None = None,
    height: float | None = None,
    path: str | None = None,
    name: str | None = None,
    color: str | None = None,
    sequence_count: int | None = None,
    sequence_start: int = 1,
    sequence_digits: int = 0,
    sequence_setup: int = 0,
) -> dict:
    if len(uvs) % 2:
        raise AttachmentError("uvs length must be even")
    n = len(uvs) // 2
    if len(triangles) % 3 or any(t < 0 or t >= n for t in triangles):
        raise AttachmentError("triangles must be index triplets < vertex count")
    att: dict[str, Any] = {"type": "mesh"}
    _common(att, name, path, color)
    att["uvs"] = [_r(v) for v in uvs]
    att["triangles"] = [int(t) for t in triangles]
    att["vertices"] = [_r(v) for v in vertices]
    if hull:
        att["hull"] = int(hull)
    if edges:
        att["edges"] = [int(e) for e in edges]
    if width:
        att["width"] = _r(width)
    if height:
        att["height"] = _r(height)
    seq = _sequence(sequence_count, sequence_start, sequence_digits, sequence_setup)
    if seq:
        att["sequence"] = seq
    return att


def grid_mesh(
    width: float,
    height: float,
    cols: int = 4,
    rows: int = 4,
    x: float = 0.0,
    y: float = 0.0,
    path: str | None = None,
    name: str | None = None,
    color: str | None = None,
) -> dict:
    """Rectangular grid mesh centered at (x, y) in bone space, uvs over the
    full image. Vertex order: hull first (counter-clockwise from the
    bottom-left), then interior vertices row by row."""
    if cols < 1 or rows < 1:
        raise AttachmentError("cols/rows must be >= 1")
    pts: dict[tuple[int, int], int] = {}
    order: list[tuple[int, int]] = []
    # Hull: bottom edge L->R, right edge B->T, top edge R->L, left edge T->B.
    for i in range(cols):
        order.append((i, 0))
    for j in range(rows):
        order.append((cols, j))
    for i in range(cols, 0, -1):
        order.append((i, rows))
    for j in range(rows, 0, -1):
        order.append((0, j))
    hull = len(order)
    for j in range(1, rows):
        for i in range(1, cols):
            order.append((i, j))
    for idx, p in enumerate(order):
        pts[p] = idx
    uvs: list[float] = []
    verts: list[float] = []
    for i, j in order:
        u, v_up = i / cols, j / rows
        uvs += [u, 1.0 - v_up]  # uv origin top-left
        verts += [x - width / 2 + u * width, y - height / 2 + v_up * height]
    tris: list[int] = []
    for j in range(rows):
        for i in range(cols):
            a, b = pts[(i, j)], pts[(i + 1, j)]
            c, d = pts[(i + 1, j + 1)], pts[(i, j + 1)]
            tris += [a, b, c, a, c, d]
    edges: list[int] = []
    for k in range(hull):
        edges += [k * 2, ((k + 1) % hull) * 2]
    return mesh(uvs, tris, verts, hull=hull, edges=edges, width=width, height=height,
                path=path, name=name, color=color)


def polygon_mesh(
    points: Sequence[Sequence[float]],
    image_width: float,
    image_height: float,
    x: float = 0.0,
    y: float = 0.0,
    path: str | None = None,
    name: str | None = None,
) -> dict:
    """Mesh from an outline given in IMAGE pixel coords (origin top-left).
    The image is assumed centered at (x, y) in bone space like a region."""
    if len(points) < 3:
        raise AttachmentError("a polygon needs at least 3 points")
    pts = [(float(p[0]), float(p[1])) for p in points]
    tris = triangulate(pts)
    uvs: list[float] = []
    verts: list[float] = []
    for px, py in pts:
        uvs += [px / image_width, py / image_height]
        verts += [x - image_width / 2 + px, y + image_height / 2 - py]
    n = len(pts)
    edges: list[int] = []
    for k in range(n):
        edges += [k * 2, ((k + 1) % n) * 2]
    return mesh(uvs, tris, verts, hull=n, edges=edges, width=image_width,
                height=image_height, path=path, name=name)


def triangulate(pts: Sequence[tuple[float, float]]) -> list[int]:
    """Ear-clipping triangulation of a simple polygon (any winding)."""
    n = len(pts)
    idx = list(range(n))
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if area < 0:
        idx.reverse()
    tris: list[int] = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[(k - 1) % m], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if _cross(a, b, c) <= 1e-9:
                continue
            if any(
                _in_tri(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)
            ):
                continue
            tris += [i0, i1, i2]
            idx.pop(k)
            break
        else:
            raise AttachmentError("polygon is self-intersecting or degenerate")
    tris += idx
    return tris


def _cross(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _in_tri(p, a, b, c) -> bool:
    d1, d2, d3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    return d1 >= 0 and d2 >= 0 and d3 >= 0


def linked_mesh(
    source: str,
    skin: str | None = None,
    source_slot: str | None = None,
    inherit_timelines: bool = True,
    width: float | None = None,
    height: float | None = None,
    path: str | None = None,
    name: str | None = None,
    color: str | None = None,
    sequence_count: int | None = None,
) -> dict:
    """Linked mesh: reuses `source` mesh geometry/weights with another image.
    4.3: `source_slot` lets the source mesh live in a different slot."""
    att: dict[str, Any] = {"type": "linkedmesh"}
    _common(att, name, path, color)
    att["source"] = source
    if skin and skin != "default":
        att["skin"] = skin
    if source_slot:
        att["slot"] = source_slot
    if not inherit_timelines:
        att["timelines"] = False
    if width:
        att["width"] = _r(width)
    if height:
        att["height"] = _r(height)
    seq = _sequence(sequence_count)
    if seq:
        att["sequence"] = seq
    return att


def _flat(points: Sequence[Sequence[float]]) -> list[float]:
    out: list[float] = []
    for p in points:
        out += [_r(p[0]), _r(p[1])]
    return out


def bounding_box(points: Sequence[Sequence[float]], color: str | None = None) -> dict:
    if len(points) < 3:
        raise AttachmentError("a bounding box needs at least 3 points")
    att: dict[str, Any] = {"type": "boundingbox", "vertexCount": len(points), "vertices": _flat(points)}
    if color:
        att["color"] = color
    return att


def clipping(
    points: Sequence[Sequence[float]],
    end_slot: str | None = None,
    convex: bool = False,
    inverse: bool = False,
    color: str | None = None,
) -> dict:
    """Clipping polygon. 4.3: `inverse` hides the inside instead of the
    outside; `convex` tells the runtime the polygon is convex (faster)."""
    if len(points) < 3:
        raise AttachmentError("a clipping polygon needs at least 3 points")
    att: dict[str, Any] = {"type": "clipping"}
    if end_slot:
        att["end"] = end_slot
    if convex:
        att["convex"] = True
    if inverse:
        att["inverse"] = True
    att["vertexCount"] = len(points)
    att["vertices"] = _flat(points)
    if color:
        att["color"] = color
    return att


def point(x: float = 0.0, y: float = 0.0, rotation: float = 0.0, color: str | None = None) -> dict:
    att: dict[str, Any] = {"type": "point"}
    if x:
        att["x"] = _r(x)
    if y:
        att["y"] = _r(y)
    if rotation:
        att["rotation"] = _r(rotation)
    if color:
        att["color"] = color
    return att


def path(
    points: Sequence[dict | Sequence[float]],
    closed: bool = False,
    constant_speed: bool = True,
    color: str | None = None,
) -> dict:
    """Bezier path. Each point is {"x","y", optional "in": [x,y], "out":
    [x,y]} (absolute handle positions) or [x, y] (smooth handles computed
    Catmull-Rom style). Curve lengths are computed for the runtime."""
    pts = []
    for p in points:
        if isinstance(p, dict):
            pts.append((float(p["x"]), float(p["y"]), p.get("in"), p.get("out")))
        else:
            pts.append((float(p[0]), float(p[1]), None, None))
    n = len(pts)
    if n < 2:
        raise AttachmentError("a path needs at least 2 points")
    verts: list[tuple[float, float]] = []
    for i, (x, y, hin, hout) in enumerate(pts):
        prev = pts[(i - 1) % n] if (closed or i > 0) else pts[i]
        nxt = pts[(i + 1) % n] if (closed or i < n - 1) else pts[i]
        tx, ty = (nxt[0] - prev[0]) / 6.0, (nxt[1] - prev[1]) / 6.0
        verts.append(tuple(hin) if hin else (x - tx, y - ty))
        verts.append((x, y))
        verts.append(tuple(hout) if hout else (x + tx, y + ty))
    # Cumulative curve lengths: curve i goes point_i -> point_i+1.
    lengths: list[float] = []
    total = 0.0
    curves = n if closed else n - 1
    for i in range(curves):
        p0 = verts[i * 3 + 1]
        c1 = verts[i * 3 + 2]
        c2 = verts[((i + 1) % n) * 3]
        p1 = verts[((i + 1) % n) * 3 + 1]
        total += _bezier_length(p0, c1, c2, p1)
        lengths.append(_r(total))
    while len(lengths) < n:
        lengths.append(_r(total))
    att: dict[str, Any] = {"type": "path"}
    if closed:
        att["closed"] = True
    if not constant_speed:
        att["constantSpeed"] = False
    att["lengths"] = lengths
    att["vertexCount"] = len(verts)
    att["vertices"] = _flat(verts)
    if color:
        att["color"] = color
    return att


def _bezier_length(p0, c1, c2, p1, steps: int = 32) -> float:
    total = 0.0
    px, py = p0
    for s in range(1, steps + 1):
        t = s / steps
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p1[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p1[1]
        total += math.hypot(x - px, y - py)
        px, py = x, y
    return total


# ----------------------------------------------------------------- weights
def unweighted_positions(att: dict) -> list[tuple[float, float]]:
    verts = att.get("vertices") or []
    t = att.get("type", "region")
    n = len(att.get("uvs") or []) // 2 if t == "mesh" else int(att.get("vertexCount", 0))
    if len(verts) != n * 2:
        raise AttachmentError("attachment is already weighted")
    return [(verts[i], verts[i + 1]) for i in range(0, len(verts), 2)]


def auto_weights(
    data: dict,
    slot: str,
    att: dict,
    bone_names: Sequence[str],
    max_influences: int = 4,
    falloff: float = 2.0,
    prune: float = 0.01,
) -> list[float]:
    """Weighted vertex array binding an unweighted vertex attachment of
    `slot` to `bone_names` (setup pose)."""
    from .pose import Pose

    pose = Pose(data)
    slot_bone = next(s["bone"] for s in data["slots"] if s["name"] == slot)
    sb = pose.bones[slot_bone]
    names = [b["name"] for b in data["bones"]]
    for b in bone_names:
        if b not in pose.bones:
            raise AttachmentError(f"bone {b!r} not found")
    out: list[float] = []
    for lx, ly in unweighted_positions(att):
        wx, wy = sb.local_to_world(lx, ly)
        scored = []
        for b in bone_names:
            bs = pose.bones[b]
            d = _seg_dist((wx, wy), (bs.worldX, bs.worldY), bs.tip)
            scored.append((1.0 / (max(d, 1e-3) ** falloff), b))
        scored.sort(reverse=True)
        scored = scored[:max_influences]
        tot = sum(w for w, _ in scored)
        scored = [(w / tot, b) for w, b in scored]
        scored = [(w, b) for w, b in scored if w >= prune] or scored[:1]
        tot = sum(w for w, _ in scored)
        out.append(len(scored))
        for w, b in scored:
            bx, by = pose.bones[b].world_to_local(wx, wy)
            out += [names.index(b), _r(bx), _r(by), round(w / tot, 5)]
    return out


def _seg_dist(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


ATTACHMENT_TYPES = fmt.ATTACHMENT_TYPES
