"""Skeleton pose evaluation: local -> world bone transforms (Spine 4.3 math).

Ported from `BonePose.updateWorldTransform` / `updateLocalTransform`
(spine-libgdx 4.3) for every inherit mode. Animations are applied the way a
single track at full alpha does (bone, slot, deform and draw order timelines).
Constraints (IK, transform, path, physics, sliders) are NOT simulated: the
preview shows the keyed pose; use the Spine CLI image export for exact output.

Used for: rig helpers that need world positions (IK targets, auto weights,
reparent keeping the world pose) and the PNG preview renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import format as fmt
from .animation import key_values, sample, sample_stepped

DEG = math.pi / 180.0
EPS = 1e-5


@dataclass
class BoneState:
    name: str
    parent: str | None
    length: float
    x: float
    y: float
    rotation: float
    scaleX: float
    scaleY: float
    shearX: float
    shearY: float
    inherit: str
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    worldX: float = 0.0
    worldY: float = 0.0

    def local_to_world(self, lx: float, ly: float) -> tuple[float, float]:
        return self.a * lx + self.b * ly + self.worldX, self.c * lx + self.d * ly + self.worldY

    def world_to_local(self, wx: float, wy: float) -> tuple[float, float]:
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-12:
            return 0.0, 0.0
        x, y = wx - self.worldX, wy - self.worldY
        return (x * self.d - y * self.b) / det, (y * self.a - x * self.c) / det

    @property
    def tip(self) -> tuple[float, float]:
        return self.local_to_world(self.length, 0.0)

    @property
    def world_rotation(self) -> float:
        return math.degrees(math.atan2(self.c, self.a))


@dataclass
class SlotState:
    name: str
    bone: str
    attachment: str | None
    color: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0])
    blend: str = "normal"
    visible: bool = True
    deform: list[float] | None = None
    sequence_index: int | None = None


class Pose:
    def __init__(
        self,
        data: dict,
        animation: str | None = None,
        time: float = 0.0,
        skeleton_x: float = 0.0,
        skeleton_y: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
    ):
        self.data = data
        self.sx, self.sy = scale_x, scale_y
        self.skx, self.sky = skeleton_x, skeleton_y
        self.bones: dict[str, BoneState] = {}
        self.order: list[str] = []
        for b in data.get("bones") or []:
            st = BoneState(
                name=b["name"],
                parent=b.get("parent"),
                length=float(b.get("length", 0)),
                x=float(b.get("x", 0)),
                y=float(b.get("y", 0)),
                rotation=float(b.get("rotation", 0)),
                scaleX=float(b.get("scaleX", 1)),
                scaleY=float(b.get("scaleY", 1)),
                shearX=float(b.get("shearX", 0)),
                shearY=float(b.get("shearY", 0)),
                inherit=b.get("inherit", "normal"),
            )
            self.bones[st.name] = st
            self.order.append(st.name)
        self.slots: dict[str, SlotState] = {}
        self.draw_order: list[str] = []
        for s in data.get("slots") or []:
            st = SlotState(
                name=s["name"],
                bone=s["bone"],
                attachment=s.get("attachment"),
                blend=s.get("blend", "normal"),
                visible=s.get("visible", True),
            )
            if s.get("color"):
                st.color = _color(s["color"], 4)
            self.slots[st.name] = st
            self.draw_order.append(st.name)
        self.time = time
        self.animation = animation
        if animation is not None:
            anims = data.get("animations") or {}
            if animation not in anims:
                raise ValueError(f"animation {animation!r} not found")
            self._apply(anims[animation], time)
        self.update_world()

    # ----------------------------------------------------------- animation
    def _apply(self, anim: dict, t: float) -> None:
        setup = {b["name"]: b for b in self.data.get("bones") or []}
        for bname, tls in (anim.get("bones") or {}).items():
            st = self.bones.get(bname)
            if st is None:
                continue
            sb = setup[bname]
            for tl, keys in (tls or {}).items():
                spec = fmt.BONE_TIMELINES.get(tl)
                if spec is None:
                    continue
                if tl == "inherit":
                    k = sample_stepped(keys, t)
                    if k is not None:
                        st.inherit = k.get("inherit", "normal")
                    continue
                v = sample(spec, keys, t)
                if v is None:
                    continue
                if tl == "rotate":
                    st.rotation = sb.get("rotation", 0) + v[0]
                elif tl == "translate":
                    st.x, st.y = sb.get("x", 0) + v[0], sb.get("y", 0) + v[1]
                elif tl == "translatex":
                    st.x = sb.get("x", 0) + v[0]
                elif tl == "translatey":
                    st.y = sb.get("y", 0) + v[0]
                elif tl == "scale":
                    st.scaleX, st.scaleY = sb.get("scaleX", 1) * v[0], sb.get("scaleY", 1) * v[1]
                elif tl == "scalex":
                    st.scaleX = sb.get("scaleX", 1) * v[0]
                elif tl == "scaley":
                    st.scaleY = sb.get("scaleY", 1) * v[0]
                elif tl == "shear":
                    st.shearX, st.shearY = sb.get("shearX", 0) + v[0], sb.get("shearY", 0) + v[1]
                elif tl == "shearx":
                    st.shearX = sb.get("shearX", 0) + v[0]
                elif tl == "sheary":
                    st.shearY = sb.get("shearY", 0) + v[0]
        for sname, tls in (anim.get("slots") or {}).items():
            st = self.slots.get(sname)
            if st is None:
                continue
            for tl, keys in (tls or {}).items():
                spec = fmt.SLOT_TIMELINES.get(tl)
                if spec is None:
                    continue
                if tl == "attachment":
                    k = sample_stepped(keys, t)
                    if k is not None:
                        st.attachment = k.get("name")
                    continue
                v = sample(spec, keys, t)
                if v is None:
                    continue
                if tl in ("rgba", "rgba2"):
                    st.color = v[:4]
                elif tl in ("rgb", "rgb2"):
                    st.color = v[:3] + [st.color[3]]
                elif tl == "alpha":
                    st.color = st.color[:3] + [v[0]]
        draw = anim.get("drawOrder")
        if draw:
            from .document import decode_draw_order

            k = sample_stepped(draw, t)
            if k is not None:
                self.draw_order = decode_draw_order(k, self.draw_order)
        for folder in anim.get("drawOrderFolder") or []:
            from .document import decode_draw_order

            k = sample_stepped(folder.get("keys") or [], t)
            fslots = folder.get("slots") or []
            if k is None or not fslots:
                continue
            new = decode_draw_order(k, fslots)
            positions = sorted(self.draw_order.index(s) for s in fslots if s in self.draw_order)
            for pos, s in zip(positions, new):
                self.draw_order[pos] = s
        self._deforms = anim.get("attachments") or {}

    # -------------------------------------------------------------- world
    def update_world(self) -> None:
        for name in self.order:
            self._update_bone(self.bones[name])

    def _update_bone(self, bn: BoneState) -> None:
        sx, sy = self.sx, self.sy
        if bn.parent is None:
            rx = (bn.rotation + bn.shearX) * DEG
            ry = (bn.rotation + 90 + bn.shearY) * DEG
            bn.a = math.cos(rx) * bn.scaleX * sx
            bn.b = math.cos(ry) * bn.scaleY * sx
            bn.c = math.sin(rx) * bn.scaleX * sy
            bn.d = math.sin(ry) * bn.scaleY * sy
            bn.worldX = bn.x * sx + self.skx
            bn.worldY = bn.y * sy + self.sky
            return
        p = self.bones[bn.parent]
        pa, pb, pc, pd = p.a, p.b, p.c, p.d
        bn.worldX = pa * bn.x + pb * bn.y + p.worldX
        bn.worldY = pc * bn.x + pd * bn.y + p.worldY
        inh = bn.inherit
        if inh == "normal":
            rx = (bn.rotation + bn.shearX) * DEG
            ry = (bn.rotation + 90 + bn.shearY) * DEG
            la, lb = math.cos(rx) * bn.scaleX, math.cos(ry) * bn.scaleY
            lc, ld = math.sin(rx) * bn.scaleX, math.sin(ry) * bn.scaleY
            bn.a, bn.b = pa * la + pb * lc, pa * lb + pb * ld
            bn.c, bn.d = pc * la + pd * lc, pc * lb + pd * ld
        elif inh == "onlyTranslation":
            rx = (bn.rotation + bn.shearX) * DEG
            ry = (bn.rotation + 90 + bn.shearY) * DEG
            bn.a = math.cos(rx) * bn.scaleX * sx
            bn.b = math.cos(ry) * bn.scaleY * sx
            bn.c = math.sin(rx) * bn.scaleX * sy
            bn.d = math.sin(ry) * bn.scaleY * sy
        elif inh == "noRotationOrReflection":
            sxi, syi = 1 / sx, 1 / sy
            pa *= sxi
            pc *= syi
            s = pa * pa + pc * pc
            if s > EPS * EPS:
                s = abs(pa * pd * syi - pb * sxi * pc) / s
                pb = pc * s
                pd = pa * s
                r = bn.rotation - math.degrees(math.atan2(pc, pa))
            else:
                pa = pc = 0.0
                r = bn.rotation - 90 + math.degrees(math.atan2(pd, pb))
            rx = (r + bn.shearX) * DEG
            ry = (r + bn.shearY + 90) * DEG
            la, lb = math.cos(rx) * bn.scaleX, math.cos(ry) * bn.scaleY
            lc, ld = math.sin(rx) * bn.scaleX, math.sin(ry) * bn.scaleY
            bn.a = (pa * la - pb * lc) * sx
            bn.b = (pa * lb - pb * ld) * sx
            bn.c = (pc * la + pd * lc) * sy
            bn.d = (pc * lb + pd * ld) * sy
        else:  # noScale, noScaleOrReflection
            sxi, syi = 1 / sx, 1 / sy
            r = bn.rotation * DEG
            cos, sin = math.cos(r), math.sin(r)
            za = (pa * cos + pb * sin) * sxi
            zc = (pc * cos + pd * sin) * syi
            s = math.sqrt(za * za + zc * zc)
            s = 1 / s if s > 1e-12 else 0.0
            za *= s
            zc *= s
            zb, zd = -zc, za
            if inh == "noScale" and ((pa * pd - pb * pc < 0) != ((sx < 0) != (sy < 0))):
                zb, zd = -zb, -zd
            rx = bn.shearX * DEG
            ry = (90 + bn.shearY) * DEG
            la, lb = math.cos(rx) * bn.scaleX, math.cos(ry) * bn.scaleY
            lc, ld = math.sin(rx) * bn.scaleX, math.sin(ry) * bn.scaleY
            bn.a = (za * la + zb * lc) * sx
            bn.b = (za * lb + zb * ld) * sx
            bn.c = (zc * la + zd * lc) * sy
            bn.d = (zc * lb + zd * ld) * sy

    # -------------------------------------------------------------- utils
    def world_to_local_transform(self, name: str, new_parent: str) -> dict[str, float]:
        """Local transform (x, y, rotation, scale, shear) that keeps bone
        `name` at its current world transform under `new_parent` (normal
        inherit), mirroring BonePose.updateLocalTransform."""
        bn = self.bones[name]
        p = self.bones[new_parent]
        pa, pb, pc, pd = p.a, p.b, p.c, p.d
        pid = 1 / (pa * pd - pb * pc)
        ia, ib, ic, id_ = pd * pid, pb * pid, pc * pid, pa * pid
        dx, dy = bn.worldX - p.worldX, bn.worldY - p.worldY
        x = dx * ia - dy * ib
        y = dy * id_ - dx * ic
        ra = ia * bn.a - ib * bn.c
        rb = ia * bn.b - ib * bn.d
        rc = id_ * bn.c - ic * bn.a
        rd = id_ * bn.d - ic * bn.b
        shear_x = 0.0
        scale_x = math.sqrt(ra * ra + rc * rc)
        if scale_x > EPS:
            det = ra * rd - rb * rc
            scale_y = det / scale_x
            shear_y = -math.degrees(math.atan2(ra * rb + rc * rd, det))
            rotation = math.degrees(math.atan2(rc, ra))
        else:
            scale_x = 0.0
            scale_y = math.sqrt(rb * rb + rd * rd)
            shear_y = 0.0
            rotation = 90 - math.degrees(math.atan2(rd, rb))
        return {
            "x": x,
            "y": y,
            "rotation": rotation,
            "scaleX": scale_x,
            "scaleY": scale_y,
            "shearX": shear_x,
            "shearY": shear_y,
        }

    def deform_for(self, skin: str, slot: str, attachment: str, t: float | None = None):
        """Deform key data for an attachment at the pose time (or None)."""
        from .animation import deform_blend

        keys = (((getattr(self, "_deforms", {}) or {}).get(skin) or {}).get(slot) or {}).get(attachment, {}).get("deform")
        if not keys:
            return None
        return deform_blend(keys, self.time if t is None else t)

    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for bn in self.bones.values():
            xs += [bn.worldX, bn.tip[0]]
            ys += [bn.worldY, bn.tip[1]]
        return min(xs), min(ys), max(xs), max(ys)


def _color(hexstr: str, n: int) -> list[float]:
    vals = [int(hexstr[i * 2 : i * 2 + 2], 16) / 255.0 for i in range(n)]
    return vals + [1.0] * (4 - n)


def setup_world_positions(data: dict) -> dict[str, tuple[float, float]]:
    pose = Pose(data)
    return {n: (b.worldX, b.worldY) for n, b in pose.bones.items()}


__all__ = ["Pose", "BoneState", "SlotState", "setup_world_positions", "key_values"]
