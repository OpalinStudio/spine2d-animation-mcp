"""Load, edit and save Spine 4.3 skeleton JSON as plain dicts.

The MCP tools are stateless: every tool takes a skeleton JSON path, loads it,
applies one edit with the functions below, validates and saves it back. That
keeps the file on disk the single source of truth (the user can open it, diff
it, import it into the Spine editor at any point) and works the same on macOS
and Windows.

Editing raw dicts (rather than a typed model) means files exported by the
Spine editor round-trip untouched, including fields this module doesn't know.

Invariants maintained here that the editor relies on:
- a bone's parent is declared before it (reparenting moves the subtree);
- weighted mesh vertices index bones by POSITION, so removing or reordering
  bones remaps those indices;
- `drawOrder` animation keys are offsets relative to the setup slot order, so
  changing the setup order re-encodes every draw order key;
- names are references: renaming a bone/slot/skin/constraint/event/animation
  rewrites every place that points at it.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Iterable

from . import format as fmt
from .validator import ValidationReport, validate_data

_MISSING = object()


class SpineEditError(ValueError):
    """An edit can't be applied (unknown name, duplicate, invalid value...)."""


# --------------------------------------------------------------------- io
def load(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise SpineEditError(f"skeleton file not found: {path}")
    if path.suffix.lower() == ".skel":
        raise SpineEditError(
            "binary .skel files can't be edited; export JSON from Spine "
            "(or run spine_export with format 'json')"
        )
    if path.suffix.lower() == ".spine":
        raise SpineEditError(
            ".spine project files are a private binary format; export the "
            "skeleton to JSON first (spine_export), edit it, then import it back"
        )
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def dumps(data: dict, pretty: bool = True) -> str:
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def save(
    data: dict, path: str | Path, validate: bool = True, pretty: bool = True
) -> ValidationReport:
    """Write the skeleton. Refuses to write structurally invalid data unless
    `validate=False`, so a bad edit never corrupts the file on disk."""
    report = validate_data(data) if validate else ValidationReport()
    if report.errors:
        raise SpineEditError(
            "edit rejected, the result would not load in Spine:\n  - "
            + "\n  - ".join(report.errors)
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps(data, pretty), encoding="utf-8")
    tmp.replace(path)
    return report


def new_skeleton(
    width: float = 0.0,
    height: float = 0.0,
    x: float = 0.0,
    y: float = 0.0,
    images: str | None = "./images/",
    audio: str | None = None,
    fps: float | None = None,
    reference_scale: float | None = None,
    root_bone: str = "root",
    version: str | None = None,
) -> dict:
    header: dict[str, Any] = {"spine": version or fmt.spine_version()}
    for k, v in (("x", x), ("y", y), ("width", width), ("height", height)):
        if v:
            header[k] = float(v)
    if fps is not None and fps != 30:
        header["fps"] = fps
    if reference_scale is not None and reference_scale != 100:
        header["referenceScale"] = reference_scale
    if images:
        header["images"] = images
    if audio:
        header["audio"] = audio
    return {
        "skeleton": header,
        "bones": [{"name": root_bone}],
        "slots": [],
        "skins": [{"name": "default", "attachments": {}}],
        "animations": {},
    }


# ---------------------------------------------------------------- helpers
def _apply(entry: dict, updates: dict, defaults: dict, keep: Iterable[str] = ()) -> None:
    """Merge `updates` into `entry`. None means "leave unchanged"; a value
    equal to the reader default removes the field (keeps files minimal)."""
    keep = set(keep)
    for k, v in updates.items():
        if v is None:
            continue
        if isinstance(v, float) and v.is_integer() and k in ("fps",):
            v = int(v)
        if k not in keep and k in defaults and defaults[k] == v:
            entry.pop(k, None)
        else:
            entry[k] = v


def _num(v: float) -> float | int:
    """Compact numbers: 10.0 -> 10, keep 6 decimals."""
    if isinstance(v, bool):
        return v
    f = round(float(v), 6)
    return int(f) if f.is_integer() and abs(f) < 1e15 else f


def bones(data: dict) -> list[dict]:
    return data.setdefault("bones", [])


def slots(data: dict) -> list[dict]:
    return data.setdefault("slots", [])


def constraints(data: dict) -> list[dict]:
    return data.setdefault("constraints", [])


def skins(data: dict) -> list[dict]:
    return data.setdefault("skins", [])


def animations(data: dict) -> dict:
    return data.setdefault("animations", {})


def find_bone(data: dict, name: str) -> dict:
    for b in bones(data):
        if b.get("name") == name:
            return b
    raise SpineEditError(f"bone {name!r} not found")


def has_bone(data: dict, name: str) -> bool:
    return any(b.get("name") == name for b in bones(data))


def bone_index(data: dict, name: str) -> int:
    for i, b in enumerate(bones(data)):
        if b.get("name") == name:
            return i
    raise SpineEditError(f"bone {name!r} not found")


def find_slot(data: dict, name: str) -> dict:
    for s in slots(data):
        if s.get("name") == name:
            return s
    raise SpineEditError(f"slot {name!r} not found")


def slot_names(data: dict) -> list[str]:
    return [s["name"] for s in slots(data)]


def find_constraint(data: dict, name: str, ctype: str | None = None) -> dict:
    matches = [
        c
        for c in constraints(data)
        if c.get("name") == name and (ctype is None or c.get("type") == ctype)
    ]
    if not matches:
        kind = f"{ctype} constraint" if ctype else "constraint"
        raise SpineEditError(f"{kind} {name!r} not found")
    if len(matches) > 1:
        raise SpineEditError(
            f"several constraints are named {name!r}; pass the constraint type"
        )
    return matches[0]


def find_skin(data: dict, name: str = "default", create: bool = False) -> dict:
    for s in skins(data):
        if s.get("name") == name:
            return s
    if create:
        skin = {"name": name, "attachments": {}}
        skins(data).append(skin)
        return skin
    raise SpineEditError(f"skin {name!r} not found")


def children_of(data: dict, name: str) -> list[str]:
    return [b["name"] for b in bones(data) if b.get("parent") == name]


def descendants(data: dict, name: str) -> list[str]:
    out: list[str] = []
    stack = [name]
    while stack:
        cur = stack.pop()
        for c in children_of(data, cur):
            out.append(c)
            stack.append(c)
    return out


# ------------------------------------------------------------------ bones
BONE_FIELDS = tuple(k for k in fmt.BONE_DEFAULTS if k != "parent")


def add_bone(data: dict, name: str, parent: str | None = None, **fields: Any) -> dict:
    if has_bone(data, name):
        raise SpineEditError(f"bone {name!r} already exists")
    if parent is None and bones(data):
        parent = bones(data)[0]["name"]
    if parent is not None:
        find_bone(data, parent)
    _check_bone_fields(fields)
    bone: dict[str, Any] = {"name": name}
    if parent is not None:
        bone["parent"] = parent
    _apply(bone, {k: _maybe_num(v) for k, v in fields.items()}, fmt.BONE_DEFAULTS)
    # Insert right after the parent's subtree so the file stays readable.
    lst = bones(data)
    if parent is None:
        lst.append(bone)
    else:
        sub = set(descendants(data, parent)) | {parent}
        pos = max(i for i, b in enumerate(lst) if b["name"] in sub) + 1
        _insert_bone(data, pos, bone)
    return bone


def _insert_bone(data: dict, pos: int, bone: dict) -> None:
    lst = bones(data)
    n = len(lst)
    lst.insert(pos, bone)
    if pos < n:
        mapping = {i: (i if i < pos else i + 1) for i in range(n)}
        _remap_weights(data, mapping)


def _maybe_num(v: Any) -> Any:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return _num(v)
    return v


def _check_bone_fields(fields: dict) -> None:
    for k, v in fields.items():
        if k not in BONE_FIELDS:
            raise SpineEditError(f"unknown bone field {k!r}; allowed: {BONE_FIELDS}")
    inh = fields.get("inherit")
    if inh is not None and inh not in fmt.INHERIT_MODES:
        raise SpineEditError(f"inherit must be one of {fmt.INHERIT_MODES}")
    _check_color(fields.get("color"), 8, "bone color")


def update_bone(data: dict, name: str, parent: str | None = None, **fields: Any) -> dict:
    bone = find_bone(data, name)
    _check_bone_fields(fields)
    if parent is not None and parent != bone.get("parent"):
        reparent_bone(data, name, parent)
    _apply(bone, {k: _maybe_num(v) for k, v in fields.items()}, fmt.BONE_DEFAULTS)
    return bone


def reparent_bone(data: dict, name: str, new_parent: str, keep_world: bool = False) -> dict:
    """Change a bone's parent. With keep_world, the bone's local transform is
    recomputed so it stays where it is on screen (setup pose)."""
    bone = find_bone(data, name)
    find_bone(data, new_parent)
    if new_parent == name or new_parent in descendants(data, name):
        raise SpineEditError("a bone can't be parented to itself or a descendant")
    if bone.get("parent") is None:
        raise SpineEditError("the root bone can't be reparented")
    if keep_world:
        from .pose import Pose

        pose = Pose(data)
        local = pose.world_to_local_transform(name, new_parent)
        for k, v in local.items():
            _apply(bone, {k: _num(v)}, fmt.BONE_DEFAULTS)
    bone["parent"] = new_parent
    # Ensure the parent precedes the moved subtree.
    lst = bones(data)
    order = [b["name"] for b in lst]
    if order.index(new_parent) > order.index(name):
        sub = [name] + descendants(data, name)
        moved = [b for b in lst if b["name"] in sub]
        rest = [b for b in lst if b["name"] not in sub]
        ppos = [b["name"] for b in rest].index(new_parent)
        # after the new parent's own subtree
        psub = set(descendants({"bones": rest}, new_parent)) | {new_parent}
        pos = max(i for i, b in enumerate(rest) if b["name"] in psub) + 1
        pos = max(pos, ppos + 1)
        new_list = rest[:pos] + moved + rest[pos:]
        new_index = {b["name"]: i for i, b in enumerate(new_list)}
        mapping = {i: new_index[n] for i, n in enumerate(order)}
        data["bones"] = new_list
        _remap_weights(data, mapping)
    return bone


def rename_bone(data: dict, old: str, new: str) -> None:
    if old == new:
        return
    if has_bone(data, new):
        raise SpineEditError(f"bone {new!r} already exists")
    find_bone(data, old)["name"] = new
    for b in bones(data):
        if b.get("parent") == old:
            b["parent"] = new
    for s in slots(data):
        if s.get("bone") == old:
            s["bone"] = new
    for c in constraints(data):
        for key in ("target", "source", "bone"):
            if c.get(key) == old:
                c[key] = new
        if "bones" in c:
            c["bones"] = [new if b == old else b for b in c["bones"]]
    for skin in skins(data):
        if "bones" in skin:
            skin["bones"] = [new if b == old else b for b in skin["bones"]]
    for anim in animations(data).values():
        _rename_key(anim.get("bones"), old, new)


def remove_bone(data: dict, name: str) -> dict:
    """Remove a bone, its descendants, their slots, and every reference."""
    bone = find_bone(data, name)
    if bone.get("parent") is None:
        raise SpineEditError("the root bone can't be removed")
    doomed = [name] + descendants(data, name)
    doomed_set = set(doomed)
    order = [b["name"] for b in bones(data)]
    # Weighted vertices must not reference removed bones.
    for skin, slot, att_name, att in iter_attachments(data):
        idx = _weighted_bone_indices(data, att)
        if idx and any(order[i] in doomed_set for i in idx):
            if find_slot(data, slot)["bone"] not in doomed_set:
                raise SpineEditError(
                    f"mesh {att_name!r} (slot {slot!r}) is weighted to "
                    f"{sorted(order[i] for i in idx if order[i] in doomed_set)}; "
                    "re-weight it before removing the bone"
                )
    removed_slots = [s["name"] for s in slots(data) if s.get("bone") in doomed_set]
    for s in removed_slots:
        remove_slot(data, s)
    keep = [b for b in bones(data) if b["name"] not in doomed_set]
    new_index = {b["name"]: i for i, b in enumerate(keep)}
    mapping = {i: new_index[n] for i, n in enumerate(order) if n in new_index}
    data["bones"] = keep
    _remap_weights(data, mapping)
    removed_constraints = []
    for c in list(constraints(data)):
        refs = set(c.get("bones") or []) | {c.get("target"), c.get("source"), c.get("bone")}
        if refs & doomed_set:
            remaining = [b for b in c.get("bones") or [] if b not in doomed_set]
            if "bones" in c and remaining and not ({c.get("target"), c.get("source"), c.get("bone")} & doomed_set):
                c["bones"] = remaining
            else:
                remove_constraint(data, c["name"], c["type"])
                removed_constraints.append(c["name"])
    for skin in skins(data):
        if "bones" in skin:
            skin["bones"] = [b for b in skin["bones"] if b not in doomed_set]
            if not skin["bones"]:
                del skin["bones"]
    for anim in animations(data).values():
        for b in doomed:
            (anim.get("bones") or {}).pop(b, None)
        _drop_empty(anim, "bones")
    return {
        "removed_bones": doomed,
        "removed_slots": removed_slots,
        "removed_constraints": removed_constraints,
    }


# ------------------------------------------------------------------ slots
SLOT_FIELDS = tuple(fmt.SLOT_DEFAULTS)


def add_slot(
    data: dict, name: str, bone: str, index: int | None = None, **fields: Any
) -> dict:
    if any(s.get("name") == name for s in slots(data)):
        raise SpineEditError(f"slot {name!r} already exists")
    find_bone(data, bone)
    _check_slot_fields(fields)
    slot: dict[str, Any] = {"name": name, "bone": bone}
    _apply(slot, fields, fmt.SLOT_DEFAULTS)
    old_order = slot_names(data)
    lst = slots(data)
    if index is None or index >= len(lst):
        lst.append(slot)
    else:
        lst.insert(max(0, index), slot)
    _reencode_draw_orders(data, old_order)
    return slot


def _check_slot_fields(fields: dict) -> None:
    for k in fields:
        if k not in SLOT_FIELDS:
            raise SpineEditError(f"unknown slot field {k!r}; allowed: {SLOT_FIELDS}")
    blend = fields.get("blend")
    if blend is not None and blend not in fmt.BLEND_MODES:
        raise SpineEditError(f"blend must be one of {fmt.BLEND_MODES}")
    _check_color(fields.get("color"), 8, "slot color")
    _check_color(fields.get("dark"), 6, "slot dark color")


def update_slot(data: dict, name: str, bone: str | None = None, **fields: Any) -> dict:
    slot = find_slot(data, name)
    _check_slot_fields(fields)
    if bone is not None:
        find_bone(data, bone)
        slot["bone"] = bone
    if fields.get("attachment") == "":
        slot.pop("attachment", None)
        fields = {k: v for k, v in fields.items() if k != "attachment"}
    _apply(slot, fields, fmt.SLOT_DEFAULTS)
    return slot


def rename_slot(data: dict, old: str, new: str) -> None:
    if old == new:
        return
    if any(s.get("name") == new for s in slots(data)):
        raise SpineEditError(f"slot {new!r} already exists")
    find_slot(data, old)["name"] = new
    for c in constraints(data):
        if c.get("type") == "path" and c.get("slot") == old:
            c["slot"] = new
    for skin in skins(data):
        _rename_key(skin.get("attachments"), old, new)
        for _, slot_atts in (skin.get("attachments") or {}).items():
            for att in slot_atts.values():
                if att.get("end") == old:
                    att["end"] = new
                if att.get("slot") == old:
                    att["slot"] = new
    for anim in animations(data).values():
        _rename_key(anim.get("slots"), old, new)
        for skin_map in (anim.get("attachments") or {}).values():
            _rename_key(skin_map, old, new)
        for key in anim.get("drawOrder") or []:
            for o in key.get("offsets") or []:
                if o.get("slot") == old:
                    o["slot"] = new
        for folder in anim.get("drawOrderFolder") or []:
            folder["slots"] = [new if s == old else s for s in folder.get("slots") or []]
            for key in folder.get("keys") or []:
                for o in key.get("offsets") or []:
                    if o.get("slot") == old:
                        o["slot"] = new


def remove_slot(data: dict, name: str) -> None:
    find_slot(data, name)
    old_order = slot_names(data)
    data["slots"] = [s for s in slots(data) if s["name"] != name]
    for c in list(constraints(data)):
        if c.get("type") == "path" and c.get("slot") == name:
            remove_constraint(data, c["name"], "path")
    for skin in skins(data):
        (skin.get("attachments") or {}).pop(name, None)
        for slot_atts in (skin.get("attachments") or {}).values():
            for att in slot_atts.values():
                if att.get("end") == name:
                    att.pop("end")
    for anim in animations(data).values():
        (anim.get("slots") or {}).pop(name, None)
        _drop_empty(anim, "slots")
        for skin_name in list((anim.get("attachments") or {})):
            anim["attachments"][skin_name].pop(name, None)
            if not anim["attachments"][skin_name]:
                del anim["attachments"][skin_name]
        _drop_empty(anim, "attachments")
        for folder in anim.get("drawOrderFolder") or []:
            if name in (folder.get("slots") or []):
                old_f = list(folder["slots"])
                orders = [decode_draw_order(k, old_f) for k in folder.get("keys") or []]
                folder["slots"] = [s for s in old_f if s != name]
                for k, o in zip(folder.get("keys") or [], orders):
                    _set_offsets(k, encode_draw_order([s for s in o if s != name], folder["slots"]))
    _reencode_draw_orders(data, old_order, removed={name})


def set_setup_draw_order(data: dict, order: list[str]) -> None:
    """Reorder the setup-pose slots (back to front)."""
    old = slot_names(data)
    if sorted(order) != sorted(old):
        missing = set(old) - set(order)
        extra = set(order) - set(old)
        raise SpineEditError(
            f"draw order must list every slot exactly once (missing {sorted(missing)}, "
            f"unknown {sorted(extra)})"
        )
    by_name = {s["name"]: s for s in slots(data)}
    data["slots"] = [by_name[n] for n in order]
    _reencode_draw_orders(data, old)


# ------------------------------------------------------------- draw order
def decode_draw_order(key: dict, setup: list[str]) -> list[str]:
    """Full draw order (slot names) described by one drawOrder key."""
    offsets = key.get("offsets")
    if offsets is None:
        return list(setup)
    n = len(setup)
    idx = {s: i for i, s in enumerate(setup)}
    draw = [-1] * n
    unchanged: list[int] = []
    orig = 0
    for o in offsets:
        i = idx[o["slot"]]
        while orig != i:
            unchanged.append(orig)
            orig += 1
        draw[orig + int(o.get("offset", 0))] = orig
        orig += 1
    while orig < n:
        unchanged.append(orig)
        orig += 1
    for i in range(n - 1, -1, -1):
        if draw[i] == -1:
            draw[i] = unchanged.pop()
    return [setup[i] for i in draw]


def encode_draw_order(order: list[str], setup: list[str]) -> list[dict] | None:
    """Offsets for a full draw order relative to the setup order (None when
    the order equals the setup order)."""
    if list(order) == list(setup):
        return None
    if sorted(order) != sorted(setup):
        raise SpineEditError("draw order must list every slot exactly once")
    new_pos = {s: i for i, s in enumerate(order)}
    return [
        {"slot": s, "offset": new_pos[s] - i}
        for i, s in enumerate(setup)
        if new_pos[s] != i
    ]


def _set_offsets(key: dict, offsets: list[dict] | None) -> None:
    if offsets:
        key["offsets"] = offsets
    else:
        key.pop("offsets", None)


def _reencode_draw_orders(data: dict, old_setup: list[str], removed: set[str] | None = None) -> None:
    new_setup = slot_names(data)
    if old_setup == new_setup:
        return
    removed = removed or set()
    added = [s for s in new_setup if s not in old_setup]
    for anim in animations(data).values():
        for key in anim.get("drawOrder") or []:
            order = [s for s in decode_draw_order(key, old_setup) if s not in removed]
            # New slots keep their setup position relative to neighbours.
            for s in added:
                pos = new_setup.index(s)
                before = new_setup[pos - 1] if pos > 0 else None
                order.insert(order.index(before) + 1 if before in order else 0, s)
            _set_offsets(key, encode_draw_order(order, new_setup))


# ------------------------------------------------------------ attachments
def iter_attachments(data: dict):
    for skin in skins(data):
        for slot, atts in (skin.get("attachments") or {}).items():
            for name, att in (atts or {}).items():
                yield skin["name"], slot, name, att


def set_attachment(
    data: dict,
    slot: str,
    name: str,
    attachment: dict,
    skin: str = "default",
    make_setup: bool = False,
) -> dict:
    find_slot(data, slot)
    sk = find_skin(data, skin, create=True)
    sk.setdefault("attachments", {}).setdefault(slot, {})[name] = attachment
    if make_setup:
        find_slot(data, slot)["attachment"] = name
    return attachment


def get_attachment(data: dict, slot: str, name: str, skin: str = "default") -> dict:
    sk = find_skin(data, skin)
    att = ((sk.get("attachments") or {}).get(slot) or {}).get(name)
    if att is None:
        raise SpineEditError(f"attachment {name!r} not found in skin {skin!r} slot {slot!r}")
    return att


def remove_attachment(data: dict, slot: str, name: str, skin: str = "default") -> None:
    sk = find_skin(data, skin)
    atts = (sk.get("attachments") or {}).get(slot) or {}
    if name not in atts:
        raise SpineEditError(f"attachment {name!r} not found in skin {skin!r} slot {slot!r}")
    del atts[name]
    if not atts:
        sk["attachments"].pop(slot, None)
    if find_slot(data, slot).get("attachment") == name and not any(
        name in ((s.get("attachments") or {}).get(slot) or {}) for s in skins(data)
    ):
        find_slot(data, slot).pop("attachment", None)
    for anim in animations(data).values():
        amap = ((anim.get("attachments") or {}).get(skin) or {}).get(slot) or {}
        amap.pop(name, None)


def _weighted_bone_indices(data: dict, att: dict) -> list[int]:
    verts = att.get("vertices")
    if not isinstance(verts, list):
        return []
    vlen = _vertex_length(att)
    if vlen is None or len(verts) == vlen:
        return []
    out, i = [], 0
    while i < len(verts):
        bc = int(verts[i])
        i += 1
        for _ in range(bc):
            out.append(int(verts[i]))
            i += 4
    return out


def _vertex_length(att: dict) -> int | None:
    t = att.get("type", "region")
    if t == "mesh" and att.get("source") is None:
        return len(att.get("uvs") or [])
    if t in ("boundingbox", "clipping", "path"):
        return int(att.get("vertexCount", 0)) * 2
    return None


def _remap_weights(data: dict, mapping: dict[int, int]) -> None:
    for _, _, _, att in iter_attachments(data):
        verts = att.get("vertices")
        vlen = _vertex_length(att)
        if not isinstance(verts, list) or vlen is None or len(verts) == vlen:
            continue
        i = 0
        while i < len(verts):
            bc = int(verts[i])
            i += 1
            for _ in range(bc):
                verts[i] = mapping[int(verts[i])]
                i += 4


# ------------------------------------------------------------------ skins
def add_skin(
    data: dict,
    name: str,
    color: str | None = None,
    bones_: list[str] | None = None,
    constraints_: list[dict] | None = None,
) -> dict:
    if any(s.get("name") == name for s in skins(data)):
        raise SpineEditError(f"skin {name!r} already exists")
    skin: dict[str, Any] = {"name": name}
    skins(data).append(skin)
    update_skin(data, name, color=color, add_bones=bones_, add_constraints=constraints_)
    skin.setdefault("attachments", {})
    return skin


def update_skin(
    data: dict,
    name: str,
    color: str | None = None,
    add_bones: list[str] | None = None,
    remove_bones: list[str] | None = None,
    add_constraints: list[dict] | None = None,
    remove_constraints: list[dict] | None = None,
) -> dict:
    """Skin bones/constraints are only active when the skin is (mark them
    `skin: true`). Constraints are given as {"name", "type"}."""
    skin = find_skin(data, name)
    if color is not None:
        _check_color(color, 8, "skin color")
        skin["color"] = color
    for b in add_bones or []:
        find_bone(data, b)["skin"] = True
        lst = skin.setdefault("bones", [])
        if b not in lst:
            lst.append(b)
    for b in remove_bones or []:
        if b in skin.get("bones", []):
            skin["bones"].remove(b)
    for c in add_constraints or []:
        con = find_constraint(data, c["name"], c.get("type"))
        con["skin"] = True
        lst = skin.setdefault(fmt.SKIN_CONSTRAINT_KEYS[con["type"]], [])
        if con["name"] not in lst:
            lst.append(con["name"])
    for c in remove_constraints or []:
        con = find_constraint(data, c["name"], c.get("type"))
        lst = skin.get(fmt.SKIN_CONSTRAINT_KEYS[con["type"]], [])
        if con["name"] in lst:
            lst.remove(con["name"])
    for key in ["bones", *fmt.SKIN_CONSTRAINT_KEYS.values()]:
        if key in skin and not skin[key]:
            del skin[key]
    return skin


def rename_skin(data: dict, old: str, new: str) -> None:
    if any(s.get("name") == new for s in skins(data)):
        raise SpineEditError(f"skin {new!r} already exists")
    find_skin(data, old)["name"] = new
    for _, _, _, att in iter_attachments(data):
        if att.get("skin") == old:
            att["skin"] = new
    for anim in animations(data).values():
        _rename_key(anim.get("attachments"), old, new)


def remove_skin(data: dict, name: str) -> None:
    if name == "default":
        raise SpineEditError("the default skin can't be removed")
    find_skin(data, name)
    for _, _, att_name, att in iter_attachments(data):
        if att.get("skin") == name:
            raise SpineEditError(f"linked mesh {att_name!r} uses skin {name!r} as source")
    data["skins"] = [s for s in skins(data) if s["name"] != name]
    for anim in animations(data).values():
        (anim.get("attachments") or {}).pop(name, None)
        _drop_empty(anim, "attachments")


def duplicate_skin(data: dict, source: str, new: str) -> dict:
    src = find_skin(data, source)
    if any(s.get("name") == new for s in skins(data)):
        raise SpineEditError(f"skin {new!r} already exists")
    skin = copy.deepcopy(src)
    skin["name"] = new
    skins(data).append(skin)
    return skin


# ------------------------------------------------------------ constraints
def add_constraint(data: dict, constraint: dict, index: int | None = None) -> dict:
    ctype = constraint.get("type")
    name = constraint.get("name")
    if ctype not in fmt.CONSTRAINT_TYPES:
        raise SpineEditError(f"constraint type must be one of {fmt.CONSTRAINT_TYPES}")
    if not name:
        raise SpineEditError("constraint needs a name")
    if any(c.get("name") == name and c.get("type") == ctype for c in constraints(data)):
        raise SpineEditError(f"{ctype} constraint {name!r} already exists")
    lst = constraints(data)
    if index is None or index >= len(lst):
        lst.append(constraint)
    else:
        lst.insert(max(0, index), constraint)
    return constraint


def update_constraint(data: dict, name: str, ctype: str | None = None, **fields: Any) -> dict:
    con = find_constraint(data, name, ctype)
    defaults = fmt.CONSTRAINT_DEFAULTS[con["type"]]
    new_name = fields.pop("new_name", None)
    for k in ("bones", "target", "source", "bone", "slot"):
        v = fields.get(k)
        if v is None:
            continue
        for bn in v if isinstance(v, list) else [v]:
            if k == "slot":
                find_slot(data, bn)
            else:
                find_bone(data, bn)
    _apply(con, {k: _maybe_num(v) for k, v in fields.items()}, defaults)
    if new_name:
        rename_constraint(data, name, new_name, con["type"])
    return con


def rename_constraint(data: dict, old: str, new: str, ctype: str | None = None) -> None:
    con = find_constraint(data, old, ctype)
    t = con["type"]
    if any(c.get("name") == new and c.get("type") == t for c in constraints(data)):
        raise SpineEditError(f"{t} constraint {new!r} already exists")
    con["name"] = new
    key = fmt.SKIN_CONSTRAINT_KEYS[t]
    for skin in skins(data):
        if old in skin.get(key, []):
            skin[key] = [new if n == old else n for n in skin[key]]
    for anim in animations(data).values():
        _rename_key(anim.get(t), old, new)


def remove_constraint(data: dict, name: str, ctype: str | None = None) -> None:
    con = find_constraint(data, name, ctype)
    t = con["type"]
    data["constraints"] = [c for c in constraints(data) if c is not con]
    key = fmt.SKIN_CONSTRAINT_KEYS[t]
    for skin in skins(data):
        if name in skin.get(key, []):
            skin[key].remove(name)
            if not skin[key]:
                del skin[key]
    for anim in animations(data).values():
        (anim.get(t) or {}).pop(name, None)
        _drop_empty(anim, t)
    if not data["constraints"]:
        del data["constraints"]


def move_constraint(data: dict, name: str, index: int, ctype: str | None = None) -> None:
    """Constraint order = update order in 4.3. Move one to `index`."""
    con = find_constraint(data, name, ctype)
    lst = constraints(data)
    lst.remove(con)
    lst.insert(max(0, min(index, len(lst))), con)


# ----------------------------------------------------------------- events
EVENT_DEFAULTS = {"int": 0, "float": 0.0, "string": "", "audio": None, "volume": 1.0, "balance": 0.0}


def set_event(data: dict, name: str, **fields: Any) -> dict:
    for k in fields:
        if k not in EVENT_DEFAULTS:
            raise SpineEditError(f"unknown event field {k!r}; allowed {tuple(EVENT_DEFAULTS)}")
    events = data.setdefault("events", {})
    ev = events.setdefault(name, {})
    _apply(ev, {k: _maybe_num(v) for k, v in fields.items()}, EVENT_DEFAULTS)
    if "audio" not in ev:
        ev.pop("volume", None)
        ev.pop("balance", None)
    return ev


def rename_event(data: dict, old: str, new: str) -> None:
    events = data.get("events") or {}
    if old not in events:
        raise SpineEditError(f"event {old!r} not found")
    if new in events:
        raise SpineEditError(f"event {new!r} already exists")
    data["events"] = {(new if k == old else k): v for k, v in events.items()}
    for anim in animations(data).values():
        for k in anim.get("events") or []:
            if k.get("name") == old:
                k["name"] = new


def remove_event(data: dict, name: str) -> None:
    events = data.get("events") or {}
    if name not in events:
        raise SpineEditError(f"event {name!r} not found")
    del events[name]
    if not events:
        data.pop("events")
    for anim in animations(data).values():
        if "events" in anim:
            anim["events"] = [k for k in anim["events"] if k.get("name") != name]
            _drop_empty(anim, "events")


# ------------------------------------------------------------------ misc
def _rename_key(mapping: dict | None, old: str, new: str) -> None:
    if not mapping or old not in mapping:
        return
    items = list(mapping.items())
    mapping.clear()
    for k, v in items:
        mapping[new if k == old else k] = v


def _drop_empty(container: dict, key: str) -> None:
    if key in container and not container[key]:
        del container[key]


def _check_color(value: Any, length: int, what: str) -> None:
    if value is None:
        return
    import re

    if not isinstance(value, str) or len(value) != length or not re.match(
        r"^[0-9a-fA-F]+$", value
    ):
        raise SpineEditError(
            f"{what} must be {length} hex digits (RRGGBB{'AA' if length == 8 else ''}), got {value!r}"
        )


def summary(data: dict) -> dict:
    """Compact overview used by the inspect tool."""
    from .animation import animation_duration

    sk = data.get("skeleton") or {}
    out: dict[str, Any] = {
        "spine_version": sk.get("spine"),
        "size": [sk.get("width", 0), sk.get("height", 0)],
        "images": sk.get("images"),
        "bones": [
            {"name": b["name"], "parent": b.get("parent")} for b in bones(data)
        ],
        "slots": [
            {"name": s["name"], "bone": s["bone"], "attachment": s.get("attachment")}
            for s in slots(data)
        ],
        "constraints": [
            {"name": c["name"], "type": c["type"]} for c in data.get("constraints") or []
        ],
        "skins": [],
        "events": sorted((data.get("events") or {}).keys()),
        "animations": [],
    }
    for skin in skins(data):
        n = sum(len(v) for v in (skin.get("attachments") or {}).values())
        types: dict[str, int] = {}
        for atts in (skin.get("attachments") or {}).values():
            for a in atts.values():
                t = a.get("type", "region")
                types[t] = types.get(t, 0) + 1
        out["skins"].append({"name": skin["name"], "attachments": n, "types": types})
    for name, anim in animations(data).items():
        out["animations"].append(
            {
                "name": name,
                "duration": round(animation_duration(anim), 4),
                "timelines": sorted(k for k in anim if k != "color"),
            }
        )
    return out


def deg(rad: float) -> float:
    return math.degrees(rad)
