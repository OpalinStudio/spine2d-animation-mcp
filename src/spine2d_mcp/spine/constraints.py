"""Builders for the five 4.3 constraint types, plus rigging helpers.

The array order of `constraints` is the update order in 4.3. Builders only
emit non-default fields (defaults from `format.py`, i.e. the 4.3 reader).

Rigging helpers build complete setups from an existing skeleton:
- `ik_for_chain`: creates a target bone at the end of a 1-2 bone chain and
  the IK constraint (legs, arms, aiming).
- `physics_chain`: one physics constraint per bone of a chain (hair, tails,
  capes, ears, antennae) with falloff along the chain.
- `slider_for_animation`: a 4.3 slider driving an animation (blend shape,
  pose library, facial expressions) from a bone property or manual time.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from . import document as doc
from . import format as fmt


class ConstraintError(ValueError):
    pass


def _clean(c: dict, defaults: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in c.items():
        if v is None:
            continue
        if k in defaults and defaults[k] == v:
            continue
        if isinstance(v, float):
            v = round(v, 6)
            if v.is_integer():
                v = int(v)
        out[k] = v
    return out


def _enum(value: Any, allowed: tuple, what: str) -> None:
    if value is not None and value not in allowed:
        raise ConstraintError(f"{what} must be one of {allowed}, got {value!r}")


def ik(
    name: str,
    bones: Sequence[str],
    target: str,
    mix: float = 1.0,
    softness: float = 0.0,
    bend_positive: bool = True,
    compress: bool = False,
    stretch: bool = False,
    scale_y: str | None = None,
    skin: bool = False,
) -> dict:
    """IK constraint. `scale_y` (4.3): with compress/stretch, how scaleY
    follows scaleX: "none", "uniform" (keep aspect) or "volume" (squash and
    stretch preserving area)."""
    if not 1 <= len(bones) <= 2:
        raise ConstraintError("IK constrains 1 or 2 bones")
    _enum(scale_y, fmt.SCALE_Y_MODES, "scale_y")
    c = {
        "type": "ik",
        "name": name,
        "skin": skin,
        "bones": list(bones),
        "target": target,
        "scaleY": None if scale_y in (None, "none") else scale_y,
        "mix": mix,
        "softness": softness,
        "bendPositive": bend_positive,
        "compress": compress,
        "stretch": stretch,
    }
    return _clean(c, fmt.IK_DEFAULTS)


def transform(
    name: str,
    source: str,
    bones: Sequence[str],
    properties: dict | None = None,
    copy: Sequence[str] | None = ("rotate", "x", "y", "scaleX", "scaleY", "shearY"),
    mix_rotate: float = 1.0,
    mix_x: float = 1.0,
    mix_y: float | None = None,
    mix_scale_x: float = 1.0,
    mix_scale_y: float | None = None,
    mix_shear_y: float = 1.0,
    offset_rotation: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_scale_x: float = 0.0,
    offset_scale_y: float = 0.0,
    offset_shear_y: float = 0.0,
    local_source: bool = False,
    local_target: bool = False,
    additive: bool = False,
    clamp: bool = False,
    skin: bool = False,
) -> dict:
    """4.3 transform constraint.

    `properties` maps a source property to constrained properties, e.g.
    {"rotate": {"to": {"scaleX": {"scale": 0.01, "max": 2}}}} makes rotating
    the source bone scale the constrained bones. `offset` on a from/to entry
    and `scale`/`max` on a to entry follow the 4.3 format; with `clamp`, `max`
    limits the constrained value. When `properties` is None, `copy` builds the
    classic identity mapping (rotate->rotate, x->x, ...).
    """
    if properties is None:
        properties = {}
        for p in copy or ():
            if p not in fmt.TRANSFORM_PROPERTIES:
                raise ConstraintError(f"copy property {p!r} not in {fmt.TRANSFORM_PROPERTIES}")
            properties[p] = {"to": {p: {}}}
    for frm, entry in properties.items():
        if frm not in fmt.TRANSFORM_PROPERTIES:
            raise ConstraintError(f"from property {frm!r} not in {fmt.TRANSFORM_PROPERTIES}")
        for to in (entry or {}).get("to", {}):
            if to not in fmt.TRANSFORM_PROPERTIES:
                raise ConstraintError(f"to property {to!r} not in {fmt.TRANSFORM_PROPERTIES}")
    tos = {t for e in properties.values() for t in (e or {}).get("to", {})}
    c: dict[str, Any] = {
        "type": "transform",
        "name": name,
        "skin": skin,
        "source": source,
        "bones": list(bones),
        "localSource": local_source,
        "localTarget": local_target,
        "additive": additive,
        "clamp": clamp,
        "rotation": offset_rotation,
        "x": offset_x,
        "y": offset_y,
        "scaleX": offset_scale_x,
        "scaleY": offset_scale_y,
        "shearY": offset_shear_y,
        "properties": properties,
    }
    out = _clean(c, fmt.TRANSFORM_DEFAULTS)
    # Mixes are read only for mapped "to" properties.
    if "rotate" in tos and mix_rotate != 1:
        out["mixRotate"] = mix_rotate
    if "x" in tos and mix_x != 1:
        out["mixX"] = mix_x
    if "y" in tos:
        my = mix_x if mix_y is None else mix_y
        if my != out.get("mixX", 1):
            out["mixY"] = my
    if "scaleX" in tos and mix_scale_x != 1:
        out["mixScaleX"] = mix_scale_x
    if "scaleY" in tos:
        msy = mix_scale_x if mix_scale_y is None else mix_scale_y
        if msy != out.get("mixScaleX", 1):
            out["mixScaleY"] = msy
    if "shearY" in tos and mix_shear_y != 1:
        out["mixShearY"] = mix_shear_y
    return out


def path(
    name: str,
    slot: str,
    bones: Sequence[str],
    position_mode: str = "percent",
    spacing_mode: str = "length",
    rotate_mode: str = "tangent",
    offset_rotation: float = 0.0,
    position: float = 0.0,
    spacing: float = 0.0,
    mix_rotate: float = 1.0,
    mix_x: float = 1.0,
    mix_y: float | None = None,
    skin: bool = False,
) -> dict:
    _enum(position_mode, fmt.POSITION_MODES, "position_mode")
    _enum(spacing_mode, fmt.SPACING_MODES, "spacing_mode")
    _enum(rotate_mode, fmt.ROTATE_MODES, "rotate_mode")
    c = {
        "type": "path",
        "name": name,
        "skin": skin,
        "bones": list(bones),
        "slot": slot,
        "positionMode": position_mode,
        "spacingMode": spacing_mode,
        "rotateMode": rotate_mode,
        "rotation": offset_rotation,
        "position": position,
        "spacing": spacing,
        "mixRotate": mix_rotate,
        "mixX": mix_x,
    }
    out = _clean(c, fmt.PATH_DEFAULTS)
    my = mix_x if mix_y is None else mix_y
    if my != mix_x:
        out["mixY"] = my
    return out


def physics(
    name: str,
    bone: str,
    x: float = 0.0,
    y: float = 0.0,
    rotate: float = 0.0,
    scale_x: float = 0.0,
    shear_x: float = 0.0,
    scale_y: str | None = None,
    limit: float = 5000.0,
    fps: int = 60,
    inertia: float = 0.5,
    strength: float = 100.0,
    damping: float = 0.85,
    mass: float = 1.0,
    wind: float = 0.0,
    gravity: float = 0.0,
    mix: float = 1.0,
    global_: Sequence[str] = (),
    skin: bool = False,
) -> dict:
    """Physics constraint. x/y/rotate/scale_x/shear_x are the 0..1 amounts of
    each affected property. `scale_y` (4.3): "uniform"/"volume" make scaleY
    follow the simulated scaleX. `global_` lists properties that use the
    skeleton-wide value (inertia, strength, damping, mass, wind, gravity,
    mix), set with physics timelines keyed on "" (all constraints)."""
    _enum(scale_y, fmt.SCALE_Y_MODES, "scale_y")
    if mass <= 0:
        raise ConstraintError("mass must be > 0")
    c: dict[str, Any] = {
        "type": "physics",
        "name": name,
        "skin": skin,
        "bone": bone,
        "x": x,
        "y": y,
        "rotate": rotate,
        "scaleX": scale_x,
        "scaleY": None if scale_y in (None, "none") else scale_y,
        "shearX": shear_x,
        "limit": limit,
        "fps": fps,
        "inertia": inertia,
        "strength": strength,
        "damping": damping,
        "mass": mass,
        "wind": wind,
        "gravity": gravity,
        "mix": mix,
    }
    for g in global_:
        if g not in ("inertia", "strength", "damping", "mass", "wind", "gravity", "mix"):
            raise ConstraintError(f"unknown global physics property {g!r}")
        c[f"{g}Global"] = True
    return _clean(c, fmt.PHYSICS_DEFAULTS)


def slider(
    name: str,
    animation: str,
    bone: str | None = None,
    property: str | None = None,
    from_: float = 0.0,
    to: float = 0.0,
    scale: float = 1.0,
    max_: float = 0.0,
    local: bool = False,
    time: float = 0.0,
    mix: float = 1.0,
    loop: bool = False,
    additive: bool = False,
    skin: bool = False,
) -> dict:
    """4.3 slider: poses the skeleton with `animation` at a time that is
    either fixed (`time`, keyable with slider timelines) or driven by a bone
    property: time = to + (bone.property - from) * scale (clamped to the
    animation unless `loop`). `max_` is the editor UI range (nonessential)."""
    c: dict[str, Any] = {
        "type": "slider",
        "name": name,
        "skin": skin,
        "additive": additive,
        "loop": loop,
        "mix": mix,
        "animation": animation,
    }
    if bone is not None:
        if property not in fmt.TRANSFORM_PROPERTIES:
            raise ConstraintError(
                f"a bone-driven slider needs property in {fmt.TRANSFORM_PROPERTIES}"
            )
        c.update({"bone": bone, "property": property, "from": from_, "to": to,
                  "scale": scale, "max": max_, "local": local})
    else:
        c["time"] = time
    return _clean(c, fmt.SLIDER_DEFAULTS)


# ------------------------------------------------------------ rig helpers
def ik_for_chain(
    data: dict,
    bones: Sequence[str],
    target_name: str | None = None,
    target_parent: str | None = None,
    constraint_name: str | None = None,
    bend_positive: bool = True,
    orient_to_child: bool = False,
    **ik_kwargs: Any,
) -> dict:
    """Create an IK target bone at the end of the chain + the constraint.

    Spine solves IK for the TIP of the last bone, not for its child. When that
    bone has no length the target goes on its first child and the result has
    a `warnings` entry (2-bone IK would send the elbow to the target); with
    orient_to_child=True the bone is first rotated and lengthened toward that
    child (see `orient_bone_to_child`), so the tip is the wrist."""
    from .pose import Pose

    for b in bones:
        doc.find_bone(data, b)
    if len(bones) == 2 and doc.find_bone(data, bones[1]).get("parent") != bones[0]:
        raise ConstraintError("for 2-bone IK the second bone must be a child of the first")
    warnings: list[str] = []
    kids = [k for k in doc.children_of(data, bones[-1])]
    if orient_to_child and kids and float(doc.find_bone(data, bones[-1]).get("length", 0)) <= 0:
        warnings += orient_bone_to_child(data, bones[-1], kids[0])["warnings"]
    pose = Pose(data)
    last = pose.bones[bones[-1]]
    if last.length > 0:
        tx, ty = last.tip
    elif kids:
        k = pose.bones[kids[0]]
        tx, ty = k.worldX, k.worldY
        off = math.degrees(math.atan2(k.y, k.x)) if (k.x or k.y) else 0.0
        if len(bones) == 2 or abs(off) > 0.5:
            warnings.append(
                f"bone {bones[-1]!r} has no length: the IK target is on its child {kids[0]!r}, "
                "but Spine solves for the bone tip, so "
                + ("the elbow will jump to the target (broken arm)" if len(bones) == 2
                   else f"the setup pose will turn by {off:.1f} deg")
                + "; pass orient_to_child=true to point the bone at its child first"
            )
    else:
        raise ConstraintError(
            f"bone {bones[-1]!r} has no length and no child: can't place the IK target "
            "(set the bone length first)"
        )
    target_parent = target_parent or data["bones"][0]["name"]
    tp = pose.bones[target_parent]
    lx, ly = tp.world_to_local(tx, ty)
    target_name = target_name or f"{bones[-1]}-ik-target"
    doc.add_bone(data, target_name, parent=target_parent, x=lx, y=ly, color="ff3f00ff")
    con = ik(
        constraint_name or f"{bones[-1]}-ik",
        bones,
        target_name,
        bend_positive=bend_positive,
        **ik_kwargs,
    )
    doc.add_constraint(data, con)
    return {"target_bone": target_name, "constraint": con, "warnings": warnings}


def _rotate_pt(x: float, y: float, cos: float, sin: float) -> tuple[float, float]:
    return x * cos - y * sin, x * sin + y * cos


def orient_bone_to_child(data: dict, bone: str, child: str | None = None) -> dict:
    """Point `bone` at `child` (rotation + length = distance) without moving
    anything in the setup pose: children, region/point attachments, unweighted
    vertices and weighted vertex entries of the bone are counter-rotated.

    Needs a uniform scale and no shear on the bone (otherwise a local rotation
    does not commute with the bone transform). Animations are not rewritten:
    `warnings` lists the timelines whose values live in the bone's local space
    (children translate, deform of its attachments) and constraints that read
    the bone's rotation."""
    b = doc.find_bone(data, bone)
    kids = doc.children_of(data, bone)
    child = child or (kids[0] if kids else None)
    if child is None or child not in kids:
        raise ConstraintError(f"bone {bone!r} has no child {child!r} to point at")
    sx, sy = float(b.get("scaleX", 1)), float(b.get("scaleY", 1))
    if abs(sx - sy) > 1e-6 or float(b.get("shearX", 0)) or float(b.get("shearY", 0)):
        raise ConstraintError(
            f"bone {bone!r} has a non-uniform scale or a shear: orient it by hand"
        )
    cb = doc.find_bone(data, child)
    px, py = float(cb.get("x", 0)), float(cb.get("y", 0))
    length = math.hypot(px, py)
    if length < 1e-6:
        raise ConstraintError(f"child {child!r} sits on the origin of {bone!r}: no direction")
    r = math.degrees(math.atan2(py, px))
    cos, sin = math.cos(math.radians(-r)), math.sin(math.radians(-r))

    def num(v: float) -> float | int:
        v = round(v, 4)
        return int(v) if v == int(v) else v

    b["rotation"] = num(float(b.get("rotation", 0)) + r)
    b["length"] = num(length)
    for k in kids:
        kb = doc.find_bone(data, k)
        x, y = _rotate_pt(float(kb.get("x", 0)), float(kb.get("y", 0)), cos, sin)
        kb["x"], kb["y"] = num(x), num(y)
        if kb.get("inherit", "normal") in ("normal", "noScale", "noScaleOrReflection"):
            kb["rotation"] = num(float(kb.get("rotation", 0)) - r)
        for f in ("x", "y", "rotation"):
            if kb.get(f) == 0:
                kb.pop(f)
    slots = {s["name"] for s in doc.slots(data) if s["bone"] == bone}
    bi = doc.bone_index(data, bone)
    touched: list[tuple[str, str, str]] = []
    for skin, slot, name, a in doc.iter_attachments(data):
        verts = a.get("vertices")
        vlen = doc._vertex_length(a)
        if isinstance(verts, list) and vlen is not None and len(verts) != vlen:
            i, hit = 0, False
            while i < len(verts):
                n = int(verts[i])
                i += 1
                for _ in range(n):
                    if int(verts[i]) == bi:
                        verts[i + 1], verts[i + 2] = (
                            num(v) for v in _rotate_pt(verts[i + 1], verts[i + 2], cos, sin))
                        hit = True
                    i += 4
            if hit:
                touched.append((skin, slot, name))
            continue
        if slot not in slots:
            continue
        t = a.get("type", "region")
        if t in ("region", "point"):
            x, y = _rotate_pt(float(a.get("x", 0)), float(a.get("y", 0)), cos, sin)
            a["x"], a["y"] = num(x), num(y)
            a["rotation"] = num(float(a.get("rotation", 0)) - r)
        elif isinstance(verts, list) and vlen is not None:
            for i in range(0, len(verts), 2):
                verts[i], verts[i + 1] = (num(v) for v in _rotate_pt(verts[i], verts[i + 1], cos, sin))
            touched.append((skin, slot, name))
    warnings: list[str] = []
    for an, anim in doc.animations(data).items():
        for k in kids:
            for tl in (anim.get("bones") or {}).get(k) or {}:
                if tl in ("translate", "translatex", "translatey"):
                    warnings.append(f"animation {an!r}: {tl} keys of {k!r} are in {bone!r} space "
                                    f"and now turn by {-r:.2f} deg; re-key them")
        for tl in (anim.get("bones") or {}).get(bone) or {}:
            if tl.startswith(("scale", "shear")):
                warnings.append(f"animation {an!r}: {tl} keys of {bone!r} may no longer match "
                                "after the reorientation; check them")
        for skin, slot, name in touched:
            if (((anim.get("attachments") or {}).get(skin) or {}).get(slot) or {}).get(name):
                warnings.append(f"animation {an!r}: deform of {slot}/{name} is in {bone!r} space; "
                                "re-key it")
    for c in doc.constraints(data):
        if c.get("type") != "ik" and (c.get("source") == bone or c.get("bone") == bone):
            warnings.append(f"constraint {c['name']!r} reads {bone!r}: its rotation changed by "
                            f"{r:.2f} deg; adjust the offsets")
    return {"bone": bone, "child": child, "rotation_delta": num(r), "length": num(length),
            "warnings": warnings}


def physics_chain(
    data: dict,
    bones: Sequence[str],
    name_prefix: str | None = None,
    rotate: float = 1.0,
    x: float = 0.0,
    y: float = 0.0,
    inertia: float = 0.5,
    strength: float = 100.0,
    damping: float = 0.85,
    mass: float = 1.0,
    gravity: float = 0.0,
    wind: float = 0.0,
    falloff: float = 0.15,
    **kwargs: Any,
) -> list[dict]:
    """One physics constraint per bone; later bones get a bit more inertia
    and less strength (`falloff`) for a natural whip."""
    out = []
    for i, b in enumerate(bones):
        doc.find_bone(data, b)
        k = 1.0 - falloff * i
        con = physics(
            f"{name_prefix}-{i + 1}" if name_prefix else f"{b}-physics",
            b,
            x=x,
            y=y,
            rotate=rotate,
            inertia=min(1.0, inertia * (1 + falloff * i)),
            strength=max(1.0, strength * max(k, 0.2)),
            damping=damping,
            mass=mass,
            gravity=gravity,
            wind=wind,
            **kwargs,
        )
        doc.add_constraint(data, con)
        out.append(con)
    return out
