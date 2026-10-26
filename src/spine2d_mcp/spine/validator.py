"""Structural validation of Spine 4.3 skeleton JSON.

Pure-Python port of the checks the 4.3 reader (`reference/SkeletonJson.java`)
performs while parsing, plus a few editor-level sanity checks (sorted keys,
curve array sizes, draw order offsets that actually decode). Catching these
here turns a failed import in the Spine editor into a precise error message.

`validate_data(dict)` works on raw JSON (what every editing tool produces),
`validate(SpineProject)` keeps the PSD builder's typed path working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import format as fmt


class SpineValidationError(ValueError):
    """Raised when skeleton data violates a Spine 4.3 structural invariant."""


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


_HEX = re.compile(r"^[0-9a-fA-F]+$")


def validate(project) -> None:
    """Typed entry point used by the PSD builder. Raises on errors."""
    from .writer import to_dict

    report = validate_data(to_dict(project))
    if report.errors:
        raise SpineValidationError(
            "SpineProject failed validation:\n  - " + "\n  - ".join(report.errors)
        )


def assert_valid(data: dict) -> ValidationReport:
    report = validate_data(data)
    if report.errors:
        raise SpineValidationError(
            "Skeleton failed validation:\n  - " + "\n  - ".join(report.errors)
        )
    return report


def _deform_length(att: dict, skin: dict, slot: str, skins: dict) -> int | None:
    """Number of deform values for a vertex attachment (DeformTimeline's
    deformLength): 2 per vertex, or 2 per bone influence when weighted."""
    if att.get("type") == "linkedmesh" or att.get("source"):
        src_skin = skins.get(att.get("skin") or "default") or {}
        att = ((src_skin.get("attachments") or {}).get(att.get("slot") or slot) or {}).get(att.get("source"))
        if att is None:
            return None
    t = att.get("type", "region")
    if t == "mesh":
        n = len(att.get("uvs") or [])
    elif t in ("boundingbox", "clipping", "path"):
        n = int(att.get("vertexCount", 0)) * 2
    else:
        return None
    verts = att.get("vertices") or []
    if len(verts) == n:
        return n
    i = influences = 0
    try:
        while i < len(verts):
            bc = int(verts[i])
            influences += bc
            i += 1 + bc * 4
    except (TypeError, ValueError):
        return None
    return influences * 2


def validate_data(data: dict) -> ValidationReport:
    v = _Validator(data)
    v.run()
    return v.report


class _Validator:
    def __init__(self, data: dict):
        self.d = data
        self.report = ValidationReport()
        self.bones: list[str] = []
        self.slots: list[str] = []
        # name -> types (names are unique per constraint type, not globally)
        self.constraints: dict[str, set[str]] = {}
        self.skins: dict[str, dict] = {}
        self.events: set[str] = set()
        self.animations: set[str] = set()

    def err(self, msg: str) -> None:
        self.report.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.report.warnings.append(msg)

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        d = self.d
        if not isinstance(d, dict):
            self.err("skeleton data must be a JSON object")
            return
        sk = d.get("skeleton")
        if sk is None:
            self.warn("missing `skeleton` header (version will be unknown)")
        elif not isinstance(sk, dict):
            self.err("`skeleton` must be an object")
        else:
            ver = sk.get("spine")
            if not ver:
                self.warn("skeleton.spine version is missing")
            elif not str(ver).startswith("4.3"):
                self.warn(f"skeleton.spine is {ver!r}; this tool targets 4.3")
        for key in ("ik", "transform", "path", "physics"):
            if key in d:
                self.err(
                    f"top-level `{key}` is the 4.2 layout; Spine 4.3 uses a single "
                    "`constraints` array with a `type` field"
                )
        anims = d.get("animations") or {}
        if isinstance(anims, dict):
            self.animations = set(anims)
        self._bones()
        self._slots()
        self._constraints()
        self._skins()
        self._events()
        self._animations()

    # ---------------------------------------------------------------- bones
    def _bones(self) -> None:
        bones = self.d.get("bones") or []
        if not bones:
            self.warn("skeleton has no bones")
        seen: set[str] = set()
        for i, b in enumerate(bones):
            name = b.get("name")
            if not name:
                self.err(f"bone #{i} has no name")
                continue
            if name in seen:
                self.err(f"duplicate bone name: {name!r}")
            parent = b.get("parent")
            if parent is not None and parent not in seen:
                self.err(
                    f"bone {name!r} has parent {parent!r} not declared before it"
                )
            if parent is None and i > 0:
                self.warn(f"bone {name!r} has no parent (only the root should)")
            inherit = b.get("inherit", "normal")
            if inherit not in fmt.INHERIT_MODES:
                self.err(f"bone {name!r}: invalid inherit {inherit!r}")
            if "transform" in b:
                self.err(
                    f"bone {name!r}: `transform` is the pre-4.2 field, use `inherit`"
                )
            self._color(b.get("color"), 8, f"bone {name!r} color")
            seen.add(name)
            self.bones.append(name)

    # ---------------------------------------------------------------- slots
    def _slots(self) -> None:
        seen: set[str] = set()
        bone_set = set(self.bones)
        for i, s in enumerate(self.d.get("slots") or []):
            name = s.get("name")
            if not name:
                self.err(f"slot #{i} has no name")
                continue
            if name in seen:
                self.err(f"duplicate slot name: {name!r}")
            seen.add(name)
            self.slots.append(name)
            if s.get("bone") not in bone_set:
                self.err(f"slot {name!r} references missing bone {s.get('bone')!r}")
            blend = s.get("blend", "normal")
            if blend not in fmt.BLEND_MODES:
                self.err(f"slot {name!r}: invalid blend {blend!r}")
            self._color(s.get("color"), 8, f"slot {name!r} color")
            self._color(s.get("dark"), 6, f"slot {name!r} dark", allow8=True)

    # ---------------------------------------------------------- constraints
    def _constraints(self) -> None:
        bone_set, slot_set = set(self.bones), set(self.slots)
        for i, c in enumerate(self.d.get("constraints") or []):
            name = c.get("name")
            ctype = c.get("type")
            where = f"constraint {name!r}"
            if not name:
                self.err(f"constraint #{i} has no name")
                continue
            if ctype not in fmt.CONSTRAINT_TYPES:
                self.err(f"{where}: invalid type {ctype!r}")
                continue
            if ctype in self.constraints.get(name, set()):
                self.err(f"duplicate {ctype} constraint name: {name!r}")
            self.constraints.setdefault(name, set()).add(ctype)
            if "order" in c:
                self.warn(
                    f"{where}: `order` is ignored in 4.3 (array position is the order)"
                )
            if ctype == "ik":
                bones = c.get("bones") or []
                if not 1 <= len(bones) <= 2:
                    self.err(f"{where}: IK needs 1 or 2 bones, got {len(bones)}")
                self._bone_refs(bones, where, bone_set)
                if c.get("target") not in bone_set:
                    self.err(f"{where}: target bone {c.get('target')!r} not found")
                if c.get("target") in bones:
                    self.err(f"{where}: target cannot be one of the constrained bones")
                self._enum(c.get("scaleY"), fmt.SCALE_Y_MODES, f"{where} scaleY")
                if "uniform" in c:
                    self.warn(f"{where}: `uniform` is 4.2; 4.3 uses scaleY: 'uniform'")
            elif ctype == "transform":
                bones = c.get("bones") or []
                if not bones:
                    self.err(f"{where}: transform constraint needs bones")
                self._bone_refs(bones, where, bone_set)
                if "target" in c and "source" not in c:
                    self.err(f"{where}: 4.3 uses `source` for the source bone, not `target`")
                if c.get("source") not in bone_set:
                    self.err(f"{where}: source bone {c.get('source')!r} not found")
                if c.get("source") in bones:
                    self.err(f"{where}: source cannot be one of the constrained bones")
                props = c.get("properties") or {}
                if not isinstance(props, dict):
                    self.err(f"{where}: properties must be an object")
                    props = {}
                for frm, entry in props.items():
                    if frm not in fmt.TRANSFORM_PROPERTIES:
                        self.err(f"{where}: invalid from property {frm!r}")
                    for to in (entry or {}).get("to", {}) or {}:
                        if to not in fmt.TRANSFORM_PROPERTIES:
                            self.err(f"{where}: invalid to property {to!r}")
                if not props:
                    self.warn(f"{where}: no properties mapped, constraint does nothing")
            elif ctype == "path":
                bones = c.get("bones") or []
                if not bones:
                    self.err(f"{where}: path constraint needs bones")
                self._bone_refs(bones, where, bone_set)
                if c.get("slot") not in slot_set:
                    self.err(f"{where}: slot {c.get('slot')!r} not found")
                self._enum(c.get("positionMode"), fmt.POSITION_MODES, f"{where} positionMode")
                self._enum(c.get("spacingMode"), fmt.SPACING_MODES, f"{where} spacingMode")
                self._enum(c.get("rotateMode"), fmt.ROTATE_MODES, f"{where} rotateMode")
            elif ctype == "physics":
                if c.get("bone") not in bone_set:
                    self.err(f"{where}: bone {c.get('bone')!r} not found")
                self._enum(c.get("scaleY"), fmt.SCALE_Y_MODES, f"{where} scaleY")
                fps = c.get("fps", 60)
                if not isinstance(fps, (int, float)) or fps <= 0:
                    self.err(f"{where}: fps must be > 0")
                if c.get("mass", 1) == 0:
                    self.err(f"{where}: mass cannot be 0")
                if not any(c.get(k, 0) for k in ("x", "y", "rotate", "scaleX", "shearX")):
                    self.warn(f"{where}: no x/y/rotate/scaleX/shearX amount, physics does nothing")
            elif ctype == "slider":
                anim = c.get("animation")
                if not anim:
                    self.err(f"{where}: slider needs an `animation`")
                elif anim not in self.animations:
                    self.err(f"{where}: slider animation {anim!r} not found")
                if c.get("bone") is not None:
                    if c.get("bone") not in bone_set:
                        self.err(f"{where}: slider bone {c.get('bone')!r} not found")
                    if c.get("property") not in fmt.TRANSFORM_PROPERTIES:
                        self.err(
                            f"{where}: bone-driven slider needs property in "
                            f"{fmt.TRANSFORM_PROPERTIES}"
                        )

    # ---------------------------------------------------------------- skins
    def _skins(self) -> None:
        skins = self.d.get("skins") or []
        if isinstance(skins, dict):
            self.err("`skins` must be an array (4.0+ format), not an object")
            return
        bone_set, slot_set = set(self.bones), set(self.slots)
        for skin in skins:
            name = skin.get("name")
            if not name:
                self.err("skin without a name")
                continue
            if name in self.skins:
                self.err(f"duplicate skin name: {name!r}")
            self.skins[name] = skin
        for name, skin in self.skins.items():
            where = f"skin {name!r}"
            self._bone_refs(skin.get("bones") or [], where, bone_set)
            for ctype, key in fmt.SKIN_CONSTRAINT_KEYS.items():
                for cname in skin.get(key) or []:
                    if ctype not in self.constraints.get(cname, set()):
                        self.err(f"{where}: {ctype} constraint {cname!r} not found")
            self._color(skin.get("color"), 8, f"{where} color")
            for slot_name, atts in (skin.get("attachments") or {}).items():
                if slot_name not in slot_set:
                    self.err(f"{where} attaches to missing slot {slot_name!r}")
                for att_name, att in (atts or {}).items():
                    self._attachment(name, slot_name, att_name, att)
        # Skin-required bones/constraints should be listed by at least one skin.
        listed_bones = {b for s in self.skins.values() for b in s.get("bones") or []}
        for b in self.d.get("bones") or []:
            if b.get("skin") and b.get("name") not in listed_bones:
                self.warn(f"bone {b.get('name')!r} is skin-required but in no skin")

    def _attachment(self, skin: str, slot: str, name: str, a: dict) -> None:
        where = f"attachment {name!r} (skin {skin!r}, slot {slot!r})"
        atype = a.get("type", "region")
        if atype not in fmt.ATTACHMENT_TYPES:
            self.err(f"{where}: invalid type {atype!r}")
            return
        self._color(a.get("color"), 8, f"{where} color")
        if atype == "region":
            for k in ("width", "height"):
                if k not in a:
                    self.err(f"{where}: region needs `{k}`")
            if a.get("width", 1) <= 0 or a.get("height", 1) <= 0:
                self.err(f"{where}: non-positive size {a.get('width')}x{a.get('height')}")
            self._sequence(a, where)
        elif atype in ("mesh", "linkedmesh"):
            self._sequence(a, where)
            if a.get("source") is not None or atype == "linkedmesh":
                self._linked(skin, slot, a, where)
                return
            uvs = a.get("uvs")
            tris = a.get("triangles")
            if not isinstance(uvs, list) or not uvs:
                self.err(f"{where}: mesh needs `uvs`")
                return
            if len(uvs) % 2:
                self.err(f"{where}: uvs length must be even")
            if not isinstance(tris, list) or not tris:
                self.err(f"{where}: mesh needs `triangles`")
            else:
                n = len(uvs) // 2
                if len(tris) % 3:
                    self.err(f"{where}: triangles length must be a multiple of 3")
                if any((not isinstance(t, int)) or t < 0 or t >= n for t in tris):
                    self.err(f"{where}: triangle index out of range (vertex count {n})")
            self._vertices(a, len(uvs), where)
            hull = a.get("hull")
            if hull is not None and (hull < 3 or hull > len(uvs) // 2):
                self.err(f"{where}: hull {hull} out of range")
        elif atype in ("boundingbox", "clipping", "path"):
            vc = a.get("vertexCount")
            if not isinstance(vc, int) or vc <= 0:
                self.err(f"{where}: needs a positive `vertexCount`")
                return
            self._vertices(a, vc * 2, where)
            if atype == "path":
                lengths = a.get("lengths")
                if not isinstance(lengths, list):
                    self.err(f"{where}: path needs `lengths`")
                elif len(lengths) != vc // 3:
                    self.err(
                        f"{where}: path lengths has {len(lengths)} entries, expected "
                        f"vertexCount/3 = {vc // 3}"
                    )
                if vc % 3:
                    self.err(f"{where}: path vertexCount must be a multiple of 3")
            if atype == "clipping":
                end = a.get("end")
                if end is not None and end not in self.slots:
                    self.err(f"{where}: clipping end slot {end!r} not found")
                if vc < 3:
                    self.err(f"{where}: clipping polygon needs at least 3 vertices")
        elif atype == "point":
            pass

    def _linked(self, skin: str, slot: str, a: dict, where: str) -> None:
        source = a.get("source") or a.get("parent")
        if "parent" in a and "source" not in a:
            self.err(f"{where}: linked mesh uses `source` in 4.3, not `parent`")
        if not source:
            self.err(f"{where}: linked mesh needs `source`")
            return
        src_skin_name = a.get("skin") or "default"
        src_skin = self.skins.get(src_skin_name)
        if src_skin is None:
            self.err(f"{where}: linked mesh skin {src_skin_name!r} not found")
            return
        src_slot = a.get("slot") or slot
        if a.get("slot") is not None and a.get("slot") not in self.slots:
            self.err(f"{where}: linked mesh source slot {a.get('slot')!r} not found")
            return
        src = ((src_skin.get("attachments") or {}).get(src_slot) or {}).get(source)
        if src is None:
            self.err(
                f"{where}: source mesh {source!r} not found in skin "
                f"{src_skin_name!r} slot {src_slot!r}"
            )
        elif src.get("type", "region") != "mesh":
            self.err(f"{where}: source {source!r} is not a mesh")

    def _sequence(self, a: dict, where: str) -> None:
        seq = a.get("sequence")
        if seq is None:
            return
        if not isinstance(seq, dict) or not isinstance(seq.get("count"), int):
            self.err(f"{where}: sequence needs an integer `count`")
            return
        if seq["count"] < 1:
            self.err(f"{where}: sequence count must be >= 1")
        setup = seq.get("setup", 0)
        if not 0 <= setup < seq["count"]:
            self.err(f"{where}: sequence setup index {setup} out of range")

    def _vertices(self, a: dict, verts_len: int, where: str) -> None:
        verts = a.get("vertices")
        if not isinstance(verts, list):
            self.err(f"{where}: needs `vertices`")
            return
        if len(verts) == verts_len:
            return  # unweighted
        # Weighted: [boneCount, (bone, x, y, weight) * boneCount] per vertex.
        i, count, nbones = 0, 0, len(self.bones)
        try:
            while i < len(verts):
                bc = int(verts[i])
                i += 1
                if bc < 1:
                    raise ValueError("vertex with no bones")
                for _ in range(bc):
                    bi = int(verts[i])
                    if not 0 <= bi < nbones:
                        self.err(f"{where}: weighted vertex bone index {bi} out of range")
                        return
                    i += 4
                count += 1
            if i != len(verts):
                raise ValueError("truncated")
        except (IndexError, ValueError, TypeError):
            self.err(
                f"{where}: vertices length {len(verts)} matches neither unweighted "
                f"({verts_len}) nor a valid weighted layout"
            )
            return
        if count * 2 != verts_len:
            self.err(
                f"{where}: weighted vertices describe {count} vertices, expected "
                f"{verts_len // 2}"
            )

    # --------------------------------------------------------------- events
    def _events(self) -> None:
        events = self.d.get("events") or {}
        if not isinstance(events, dict):
            self.err("`events` must be an object keyed by event name")
            return
        self.events = set(events)

    # ----------------------------------------------------------- animations
    def _animations(self) -> None:
        anims = self.d.get("animations") or {}
        if not isinstance(anims, dict):
            self.err("`animations` must be an object keyed by animation name")
            return
        for name, anim in anims.items():
            self._animation(name, anim or {})

    def _animation(self, name: str, a: dict) -> None:
        where = f"animation {name!r}"
        for key in a:
            if key not in fmt.ANIMATION_KEYS:
                self.warn(f"{where}: unknown key {key!r} (ignored by the reader)")
        self._color(a.get("color"), 8, f"{where} color")
        slot_set, bone_set = set(self.slots), set(self.bones)
        for slot, tls in (a.get("slots") or {}).items():
            if slot not in slot_set:
                self.err(f"{where}: slot {slot!r} not found")
            for tl, keys in (tls or {}).items():
                spec = fmt.SLOT_TIMELINES.get(tl)
                if spec is None:
                    self.err(f"{where}: slot {slot!r} has unknown timeline {tl!r}")
                    continue
                self._keys(keys, spec, f"{where} slot {slot!r} {tl}")
        for bone, tls in (a.get("bones") or {}).items():
            if bone not in bone_set:
                self.err(f"{where}: bone {bone!r} not found")
            for tl, keys in (tls or {}).items():
                spec = fmt.BONE_TIMELINES.get(tl)
                if spec is None:
                    self.warn(f"{where}: bone {bone!r} has unknown timeline {tl!r} (ignored)")
                    continue
                self._keys(keys, spec, f"{where} bone {bone!r} {tl}")
                if tl == "inherit":
                    for k in keys or []:
                        if k.get("inherit", "normal") not in fmt.INHERIT_MODES:
                            self.err(f"{where} bone {bone!r}: invalid inherit key")
        for ctype in fmt.CONSTRAINT_TYPES:
            for cname, body in (a.get(ctype) or {}).items():
                if ctype == "physics" and cname == "":
                    pass  # applies to all physics constraints
                elif ctype not in self.constraints.get(cname, set()):
                    self.err(f"{where}: {ctype} constraint {cname!r} not found")
                specs = fmt.constraint_timeline_specs(ctype)
                if "" in specs:
                    self._keys(body, specs[""], f"{where} {ctype} {cname!r}")
                    continue
                for tl, keys in (body or {}).items():
                    spec = specs.get(tl)
                    if spec is None:
                        self.warn(f"{where}: {ctype} {cname!r} unknown timeline {tl!r}")
                        continue
                    self._keys(keys, spec, f"{where} {ctype} {cname!r} {tl}")
        for skin, slots in (a.get("attachments") or {}).items():
            sk = self.skins.get(skin)
            if sk is None:
                self.err(f"{where}: attachment timelines reference missing skin {skin!r}")
                continue
            for slot, atts in (slots or {}).items():
                if slot not in slot_set:
                    self.err(f"{where}: attachment timeline slot {slot!r} not found")
                    continue
                for att, tls in (atts or {}).items():
                    attachment = ((sk.get("attachments") or {}).get(slot) or {}).get(att)
                    if attachment is None:
                        self.err(
                            f"{where}: timeline attachment {att!r} not in skin "
                            f"{skin!r} slot {slot!r}"
                        )
                        continue
                    for tl, keys in (tls or {}).items():
                        if tl == "deform":
                            if attachment.get("type", "region") not in (
                                "mesh", "linkedmesh", "boundingbox", "clipping", "path"
                            ):
                                self.err(f"{where}: deform on non-vertex attachment {att!r}")
                            self._keys(keys, fmt.DEFORM_TIMELINE, f"{where} deform {att!r}")
                            limit = _deform_length(attachment, sk, slot, self.skins)
                            for k in keys or []:
                                n = len(k.get("vertices") or []) + int(k.get("offset", 0))
                                if limit is not None and n > limit:
                                    self.err(
                                        f"{where}: deform key for {att!r} has {n} values, the "
                                        f"attachment only has {limit} (vertex or weight offsets x2)"
                                    )
                        elif tl == "sequence":
                            for k in keys or []:
                                if k.get("mode", "hold") not in fmt.SEQUENCE_MODES:
                                    self.err(f"{where}: invalid sequence mode {k.get('mode')!r}")
                            self._keys(keys, fmt.SEQUENCE_TIMELINE, f"{where} sequence {att!r}")
                        else:
                            self.warn(f"{where}: unknown attachment timeline {tl!r}")
        draw = a.get("drawOrder")
        if draw is not None:
            self._keys(draw, fmt.SEQUENCE_TIMELINE, f"{where} drawOrder")
            for k in draw:
                self._draw_offsets(k, self.slots, f"{where} drawOrder")
        for i, folder in enumerate(a.get("drawOrderFolder") or []):
            fslots = folder.get("slots") or []
            for s in fslots:
                if s not in slot_set:
                    self.err(f"{where}: drawOrderFolder #{i} slot {s!r} not found")
            keys = folder.get("keys") or []
            self._keys(keys, fmt.SEQUENCE_TIMELINE, f"{where} drawOrderFolder #{i}")
            for k in keys:
                self._draw_offsets(k, fslots, f"{where} drawOrderFolder #{i}")
        events = a.get("events")
        if events is not None:
            self._keys(events, fmt.SEQUENCE_TIMELINE, f"{where} events")
            for k in events:
                if k.get("name") not in self.events:
                    self.err(f"{where}: event {k.get('name')!r} not defined")

    def _keys(self, keys: Any, spec: fmt.TimelineSpec, where: str) -> None:
        if not isinstance(keys, list):
            self.err(f"{where}: keys must be an array")
            return
        last = -1.0
        for i, k in enumerate(keys):
            if not isinstance(k, dict):
                self.err(f"{where}: key #{i} must be an object")
                continue
            t = k.get("time", 0)
            if not isinstance(t, (int, float)) or t < 0:
                self.err(f"{where}: key #{i} has invalid time {t!r}")
                continue
            if t < last:
                self.err(f"{where}: keys not sorted by time ({t} after {last})")
            last = t
            curve = k.get("curve")
            if curve is None:
                continue
            if not spec.curve:
                self.warn(f"{where}: key #{i} curve ignored for this timeline")
            elif isinstance(curve, str):
                if curve != "stepped":
                    self.err(f"{where}: key #{i} curve string must be 'stepped'")
            elif isinstance(curve, list):
                if len(curve) != 4 * spec.value_count:
                    self.err(
                        f"{where}: key #{i} curve has {len(curve)} numbers, expected "
                        f"{4 * spec.value_count}"
                    )
            else:
                self.err(f"{where}: key #{i} invalid curve {curve!r}")
            if spec.kind == "color":
                for fld, n in spec.color_fields:
                    if fld not in k:
                        self.err(f"{where}: key #{i} missing `{fld}`")
                    else:
                        self._color(k[fld], 2 * n, f"{where} key #{i} {fld}")

    def _draw_offsets(self, key: dict, order: list[str], where: str) -> None:
        offsets = key.get("offsets")
        if offsets is None:
            return
        n = len(order)
        idx = {s: i for i, s in enumerate(order)}
        draw = [-1] * n
        last = -1
        for o in offsets:
            s = o.get("slot")
            if s not in idx:
                self.err(f"{where}: offset slot {s!r} not in the slot list")
                return
            i = idx[s]
            if i <= last:
                self.err(f"{where}: offsets must be listed in setup order")
                return
            last = i
            j = i + int(o.get("offset", 0))
            if not 0 <= j < n or draw[j] != -1:
                self.err(f"{where}: offset for slot {s!r} lands on an invalid position")
                return
            draw[j] = i

    # -------------------------------------------------------------- helpers
    def _bone_refs(self, bones: list, where: str, bone_set: set[str]) -> None:
        for bn in bones:
            if bn not in bone_set:
                self.err(f"{where}: bone {bn!r} not found")

    def _enum(self, value: Any, allowed: tuple[str, ...], where: str) -> None:
        if value is not None and value not in allowed:
            self.err(f"{where}: invalid value {value!r}, expected one of {allowed}")

    def _color(self, value: Any, length: int, where: str, allow8: bool = False) -> None:
        if value is None:
            return
        ok_len = len(value) == length or (allow8 and len(value) == 8)
        if not isinstance(value, str) or not ok_len or not _HEX.match(value):
            self.err(f"{where}: color {value!r} must be {length} hex digits")
