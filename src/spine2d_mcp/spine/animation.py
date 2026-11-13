"""Animation timelines: writing keys (with curve conversion) and sampling them.

Writing: `set_keys()` takes friendly keys (`{"time": 0.5, "value": 30,
"curve": "easeOut"}`), converts curve specs to Spine's absolute bezier
arrays against the next key, and stores them at the right place in the
animation object for any of the 4.3 timeline kinds:

    kind        target                      timelines
    bone        bone name                   rotate, translate, translatex/y,
                                            scale, scalex/y, shear, shearx/y,
                                            inherit
    slot        slot name                   attachment, rgba, rgb, alpha,
                                            rgba2, rgb2
    ik          IK constraint name          (single timeline: mix, softness,
                                            bendPositive, compress, stretch)
    transform   transform constraint name   (single: mixRotate, mixX, mixY,
                                            mixScaleX, mixScaleY, mixShearY)
    path        path constraint name        position, spacing, mix
    physics     physics constraint name     reset, inertia, strength, damping,
                ("" = all constraints)      mass, wind, gravity, mix
    slider      slider name                 time, mix
    deform      "skin/slot/attachment"      (vertices offsets, blend curve)
    sequence    "skin/slot/attachment"      (mode, index, delay)
    drawOrder   -                           full slot order per key
    events      -                           name, int, float, string, volume,
                                            balance

Sampling: `sample()` evaluates a timeline at a time exactly like the runtime
(linear / stepped / bezier), used by the preview renderer and the tests.
"""

from __future__ import annotations

import copy
from typing import Any

from . import format as fmt
from .curves import bezier_value, split_bezier, to_spine_curve

TIMELINE_KINDS = (
    "bone",
    "slot",
    "ik",
    "transform",
    "path",
    "physics",
    "slider",
    "deform",
    "sequence",
    "drawOrder",
    "events",
)


class AnimationError(ValueError):
    pass


# ------------------------------------------------------------- utilities
def _r(v: float) -> float | int:
    f = round(float(v), 6)
    if f == 0:
        return 0
    return int(f) if f.is_integer() else f


def key_time(k: dict) -> float:
    return float(k.get("time", 0.0))


def animation_duration(anim: dict) -> float:
    """Duration = time of the last key across every timeline."""
    best = 0.0

    def scan(keys: Any) -> None:
        nonlocal best
        if isinstance(keys, list) and keys:
            for k in keys:
                if isinstance(k, dict):
                    best = max(best, key_time(k))

    for group in ("slots", "bones", "path", "physics", "slider"):
        for tls in (anim.get(group) or {}).values():
            for keys in (tls or {}).values():
                scan(keys)
    for group in ("ik", "transform"):
        for keys in (anim.get(group) or {}).values():
            scan(keys)
    for skin in (anim.get("attachments") or {}).values():
        for slot in skin.values():
            for att in slot.values():
                for keys in att.values():
                    scan(keys)
    scan(anim.get("drawOrder"))
    scan(anim.get("events"))
    for folder in anim.get("drawOrderFolder") or []:
        scan(folder.get("keys"))
    return best


def spec_for(kind: str, timeline: str | None) -> fmt.TimelineSpec:
    if kind == "bone":
        table = fmt.BONE_TIMELINES
    elif kind == "slot":
        table = fmt.SLOT_TIMELINES
    elif kind in ("ik", "transform", "path", "physics", "slider"):
        table = fmt.constraint_timeline_specs(kind)
        if "" in table:
            return table[""]
    elif kind == "deform":
        return fmt.DEFORM_TIMELINE
    elif kind in ("sequence", "drawOrder", "events"):
        return fmt.SEQUENCE_TIMELINE
    else:
        raise AnimationError(f"unknown timeline kind {kind!r}; use one of {TIMELINE_KINDS}")
    if timeline not in table:
        raise AnimationError(
            f"unknown {kind} timeline {timeline!r}; use one of {sorted(table)}"
        )
    return table[timeline]


def parse_color(hexstr: str, n: int) -> list[float]:
    return [int(hexstr[i * 2 : i * 2 + 2], 16) / 255.0 for i in range(n)]


def key_values(spec: fmt.TimelineSpec, key: dict) -> list[float]:
    """Numeric values of a key in curve order, reader defaults applied."""
    if spec.kind == "color":
        out: list[float] = []
        for fld, n in spec.color_fields:
            out.extend(parse_color(key[fld], n))
        return out
    vals: list[float] = []
    resolved: dict[str, float] = {}
    for name, default in zip(spec.values, spec.defaults):
        if name == "__blend":
            vals.append(0.0)
            continue
        if name in key:
            v = float(key[name])
        elif name in spec.default_from:
            v = resolved[spec.default_from[name]]
        else:
            v = default
        resolved[name] = v
        vals.append(v)
    return vals


# ----------------------------------------------------------- key writing
def _container(anim: dict, kind: str, target: str | None, timeline: str | None, create: bool):
    """Return (parent_dict, key) where parent_dict[key] is the key list."""
    if kind in ("drawOrder", "events"):
        return anim, kind
    if target is None:
        raise AnimationError(f"{kind} timelines need a target")
    if kind == "bone":
        return _nested(anim, ["bones", target], create), timeline
    if kind == "slot":
        return _nested(anim, ["slots", target], create), timeline
    if kind in ("ik", "transform"):
        return _nested(anim, [kind], create), target
    if kind in ("path", "physics", "slider"):
        return _nested(anim, [kind, target], create), timeline
    if kind in ("deform", "sequence"):
        parts = target.split("/")
        if len(parts) == 2:
            parts = ["default", *parts]
        if len(parts) != 3:
            raise AnimationError(
                f"{kind} target must be 'skin/slot/attachment' or 'slot/attachment'"
            )
        return _nested(anim, ["attachments", *parts], create), kind
    raise AnimationError(f"unknown timeline kind {kind!r}")


def _nested(root: dict, path: list[str], create: bool) -> dict:
    cur = root
    for p in path:
        if p not in cur:
            if not create:
                return {}
            cur[p] = {}
        cur = cur[p]
    return cur


def get_keys(anim: dict, kind: str, target: str | None = None, timeline: str | None = None) -> list[dict]:
    parent, key = _container(anim, kind, target, timeline, create=False)
    return parent.get(key) or []


def _stray_numbers(k: dict, allowed: set[str]) -> list[str]:
    return [
        f for f, v in k.items()
        if f not in allowed and isinstance(v, (int, float)) and not isinstance(v, bool)
    ]


def _fix_value_field(timeline: str, k: dict, notes: list[str] | None) -> None:
    """Single-value timelines read only `value`; any other number is ignored
    by the reader (default used, the clip does not move). An axis field that
    matches the timeline (`y` on translatey) is renamed, the rest refused."""
    if "value" in k:
        return
    stray = _stray_numbers(k, {"time", "curve"})
    if not stray:
        return
    axis = timeline[-1] if timeline[-1] in "xy" and timeline[:-1] in (
        "translate", "scale", "shear") else None
    if axis and stray == [axis]:
        k["value"] = k.pop(axis)
        if notes is not None:
            msg = (f"{timeline}: keys written with `{axis}` were stored as `value` "
                   f"(the reader only reads `value` on this timeline)")
            if msg not in notes:
                notes.append(msg)
        return
    raise AnimationError(
        f"{timeline} keys take `value`, got {', '.join(f'`{f}`' for f in stray)}: "
        f"the reader would ignore {'it' if len(stray) == 1 else 'them'} and use the default"
    )


def _normalize_input_key(
    kind: str, timeline: str | None, spec: fmt.TimelineSpec, k: dict,
    notes: list[str] | None = None,
) -> dict:
    if not isinstance(k, dict):
        raise AnimationError(f"each key must be an object, got {k!r}")
    k = dict(k)
    if "time" not in k:
        k["time"] = 0.0
    if not isinstance(k["time"], (int, float)) or k["time"] < 0:
        raise AnimationError(f"invalid key time {k['time']!r}")
    # Friendly aliases.
    if kind == "bone" and timeline == "rotate" and "angle" in k and "value" not in k:
        k["value"] = k.pop("angle")
    if kind == "bone" and spec.values == ("x", "y") and "value" in k:
        v = k.pop("value")
        if isinstance(v, (list, tuple)):
            k["x"], k["y"] = v
        else:
            k["x"] = k["y"] = v
    if spec.values == ("value",):
        _fix_value_field(timeline or kind, k, notes)
    if spec.kind == "color":
        for fld, n in spec.color_fields:
            if fld not in k:
                raise AnimationError(f"{timeline} key needs `{fld}` ({2 * n} hex digits)")
            c = str(k[fld]).lstrip("#")
            if len(c) == 6 and n == 4:
                c += "ff"
            if len(c) != 2 * n:
                raise AnimationError(f"{timeline} `{fld}` must have {2 * n} hex digits")
            k[fld] = c.lower()
    if kind == "slot" and timeline == "attachment" and "name" not in k:
        k["name"] = None
    if kind == "bone" and timeline == "inherit":
        if k.get("inherit", "normal") not in fmt.INHERIT_MODES:
            raise AnimationError(f"inherit must be one of {fmt.INHERIT_MODES}")
    if kind == "sequence":
        if k.get("mode", "hold") not in fmt.SEQUENCE_MODES:
            raise AnimationError(f"sequence mode must be one of {fmt.SEQUENCE_MODES}")
    for name in spec.values:
        if name in k and name != "__blend" and not isinstance(k[name], (int, float)):
            raise AnimationError(f"`{name}` must be a number, got {k[name]!r}")
    return k


def set_keys(
    anim: dict,
    kind: str,
    target: str | None,
    timeline: str | None,
    keys: list[dict],
    mode: str = "merge",
    fps: float | None = None,
    notes: list[str] | None = None,
) -> list[dict]:
    """Write keys into a timeline.

    `notes` (optional list) receives a message for each key field that was
    renamed (e.g. `y` -> `value` on a translatey timeline).

    mode "replace" discards the existing keys; "merge" keeps them and replaces
    keys at the same time. Curves of the new keys are converted against their
    next key; existing bezier curves whose segment changed are rescaled.
    """
    if kind == "drawOrder":
        raise AnimationError("use set_draw_order_keys for draw order timelines")
    spec = spec_for(kind, timeline)
    parent, key = _container(anim, kind, target, timeline, create=True)
    existing = [] if mode == "replace" else copy.deepcopy(parent.get(key) or [])
    if mode not in ("merge", "replace"):
        raise AnimationError("mode must be 'merge' or 'replace'")

    # Normalize existing absolute curves so they can follow segment changes.
    norm_existing: list[tuple[dict, Any]] = []
    for i, k in enumerate(existing):
        nxt = existing[i + 1] if i + 1 < len(existing) else None
        norm_existing.append((k, _normalize_curve(spec, k, nxt)))

    new: list[tuple[dict, Any]] = []
    for raw in keys:
        k = _normalize_input_key(kind, timeline, spec, raw, notes)
        if fps:
            k["time"] = round(k["time"] * fps) / fps
        new.append((k, k.pop("curve", None)))

    by_time: dict[float, tuple[dict, Any, bool]] = {}
    for k, c in norm_existing:
        by_time[round(key_time(k), 6)] = (k, c, False)
    for k, c in new:
        by_time[round(key_time(k), 6)] = (k, c, True)
    merged = [by_time[t] for t in sorted(by_time)]

    out: list[dict] = []
    for i, (k, curve, _is_new) in enumerate(merged):
        k = {kk: vv for kk, vv in k.items() if kk != "curve"}
        nxt = merged[i + 1][0] if i + 1 < len(merged) else None
        if curve is not None and nxt is not None and spec.curve:
            if spec.values == ("__blend",):
                v1, v2 = [0.0], [1.0]
            else:
                v1, v2 = key_values(spec, k), key_values(spec, nxt)
            c = to_spine_curve(curve, key_time(k), key_time(nxt), v1, v2)
            if c is not None:
                k["curve"] = c
        out.append(_tidy_key(k))
    parent[key] = out
    return out


def _normalize_curve(spec: fmt.TimelineSpec, k: dict, nxt: dict | None) -> Any:
    """Absolute curve of k -> normalized spec (relative to its segment)."""
    curve = k.get("curve")
    if curve is None or isinstance(curve, str) or nxt is None or not spec.curve:
        return curve
    t1, t2 = key_time(k), key_time(nxt)
    if spec.values == ("__blend",):
        v1, v2 = [0.0], [1.0]
    else:
        v1, v2 = key_values(spec, k), key_values(spec, nxt)
    if t2 <= t1 or len(curve) != 4 * len(v1):
        return {"raw": curve}
    # A single normalized bezier can't represent per-value curves exactly;
    # keep per-value normalized control points.
    per_value = []
    for i, (a, b) in enumerate(zip(v1, v2)):
        cx1, cy1, cx2, cy2 = curve[i * 4 : i * 4 + 4]
        x1 = (cx1 - t1) / (t2 - t1)
        x2 = (cx2 - t1) / (t2 - t1)
        dv = b - a
        if abs(dv) < 1e-9:
            y1, y2 = x1, x2
        else:
            y1, y2 = (cy1 - a) / dv, (cy2 - a) / dv
        per_value.append((min(max(x1, 0), 1), y1, min(max(x2, 0), 1), y2))
    return {"per_value": per_value}


def _tidy_key(k: dict) -> dict:
    out: dict[str, Any] = {}
    for kk, vv in k.items():
        if kk == "time":
            if vv:
                out["time"] = _r(vv)
            continue
        if isinstance(vv, float):
            vv = _r(vv)
        out[kk] = vv
    # Keep "time" first for readability.
    if "time" in out:
        out = {"time": out.pop("time"), **out}
    return out


def clear_timeline(anim: dict, kind: str, target: str | None, timeline: str | None) -> bool:
    parent, key = _container(anim, kind, target, timeline, create=False)
    if key in parent:
        del parent[key]
        _prune(anim)
        return True
    return False


def _prune(obj: Any) -> None:
    if isinstance(obj, dict):
        for k in list(obj):
            v = obj[k]
            _prune(v)
            if isinstance(v, dict) and not v and k != "color":
                del obj[k]


# --------------------------------------------------------- event / order
def set_event_keys(anim: dict, keys: list[dict], mode: str = "merge") -> list[dict]:
    """Event keys: {"time", "name", optional int/float/string/volume/balance}."""
    existing = [] if mode == "replace" else list(anim.get("events") or [])
    for k in keys:
        if "name" not in k:
            raise AnimationError("event keys need a `name`")
        existing.append(_tidy_key({"time": k.get("time", 0), **{x: y for x, y in k.items() if x != "time"}}))
    existing.sort(key=key_time)
    anim["events"] = existing
    return existing


def set_draw_order_keys(
    anim: dict,
    setup_order: list[str],
    keys: list[dict],
    mode: str = "merge",
) -> list[dict]:
    """Draw order keys given as full orders: {"time", "order": [slots back to
    front]} (or "order": null to return to the setup order)."""
    from .document import encode_draw_order

    existing = [] if mode == "replace" else list(anim.get("drawOrder") or [])
    by_time = {round(key_time(k), 6): k for k in existing}
    for k in keys:
        order = k.get("order")
        new: dict[str, Any] = {}
        if k.get("time"):
            new["time"] = _r(k["time"])
        if order is not None:
            if "offsets" in k:
                new["offsets"] = k["offsets"]
            else:
                offsets = encode_draw_order(_complete_order(order, setup_order), setup_order)
                if offsets:
                    new["offsets"] = offsets
        elif "offsets" in k:
            new["offsets"] = k["offsets"]
        by_time[round(float(k.get("time", 0)), 6)] = new
    out = [by_time[t] for t in sorted(by_time)]
    anim["drawOrder"] = out
    return out


def _complete_order(order: list[str], setup: list[str]) -> list[str]:
    """Allow partial orders: listed slots are placed in that relative order at
    the positions they collectively occupy in the setup order."""
    unknown = [s for s in order if s not in setup]
    if unknown:
        raise AnimationError(f"unknown slots in draw order: {unknown}")
    if len(set(order)) != len(order):
        raise AnimationError("draw order lists a slot twice")
    if len(order) == len(setup):
        return list(order)
    listed = set(order)
    positions = [i for i, s in enumerate(setup) if s in listed]
    out = list(setup)
    for pos, s in zip(positions, order):
        out[pos] = s
    return out


def set_draw_order_folder_keys(
    anim: dict,
    folder_slots: list[str],
    keys: list[dict],
    mode: str = "merge",
) -> dict:
    """4.3 draw order folder timeline: keys reorder only `folder_slots`
    (a draw-order folder in the editor), independent of other folders."""
    from .document import encode_draw_order

    folders = anim.setdefault("drawOrderFolder", [])
    folder = next((f for f in folders if f.get("slots") == list(folder_slots)), None)
    if folder is None:
        folder = {"slots": list(folder_slots), "keys": []}
        folders.append(folder)
    existing = [] if mode == "replace" else list(folder.get("keys") or [])
    by_time = {round(key_time(k), 6): k for k in existing}
    for k in keys:
        new: dict[str, Any] = {}
        if k.get("time"):
            new["time"] = _r(k["time"])
        order = k.get("order")
        if order is not None:
            offsets = encode_draw_order(_complete_order(order, list(folder_slots)), list(folder_slots))
            if offsets:
                new["offsets"] = offsets
        by_time[round(float(k.get("time", 0)), 6)] = new
    folder["keys"] = [by_time[t] for t in sorted(by_time)]
    return folder


# ------------------------------------------------------------- retiming
def retime(anim: dict, factor: float = 1.0, offset: float = 0.0) -> None:
    """Scale every key time by `factor` then shift by `offset` (curves too)."""
    if factor <= 0:
        raise AnimationError("factor must be > 0")

    def fix_keys(keys: list, timeline_values: int | None) -> None:
        for k in keys:
            t = key_time(k) * factor + offset
            if t < 0:
                raise AnimationError("retiming would move keys before 0")
            if t:
                k["time"] = _r(t)
            else:
                k.pop("time", None)
            c = k.get("curve")
            if isinstance(c, list):
                for i in range(0, len(c), 2):
                    c[i] = _r(c[i] * factor + offset)

    _walk_keys(anim, fix_keys)


def _walk_keys(anim: dict, fn) -> None:
    for group in ("slots", "bones", "path", "physics", "slider"):
        for tls in (anim.get(group) or {}).values():
            for keys in (tls or {}).values():
                fn(keys, None)
    for group in ("ik", "transform"):
        for keys in (anim.get(group) or {}).values():
            fn(keys, None)
    for skin in (anim.get("attachments") or {}).values():
        for slot in skin.values():
            for att in slot.values():
                for keys in att.values():
                    fn(keys, None)
    for k in ("drawOrder", "events"):
        if anim.get(k):
            fn(anim[k], None)
    for folder in anim.get("drawOrderFolder") or []:
        fn(folder.get("keys") or [], None)


# ---------------------------------------------------------- key editing
def iter_timelines(anim: dict):
    """Every timeline of an animation as (kind, target, timeline, container,
    key, spec): the key list is `container[key]`; spec is None for events."""
    for group, kind, table in (("bones", "bone", fmt.BONE_TIMELINES), ("slots", "slot", fmt.SLOT_TIMELINES)):
        for target, tls in (anim.get(group) or {}).items():
            for tl in list(tls or {}):
                yield kind, target, tl, tls, tl, table.get(tl)
    for kind in ("ik", "transform"):
        for target in list(anim.get(kind) or {}):
            yield kind, target, None, anim[kind], target, fmt.constraint_timeline_specs(kind)[""]
    for kind in ("path", "physics", "slider"):
        for target, tls in (anim.get(kind) or {}).items():
            for tl in list(tls or {}):
                yield kind, target, tl, tls, tl, fmt.constraint_timeline_specs(kind).get(tl)
    for skin, slots_ in (anim.get("attachments") or {}).items():
        for slot, atts in slots_.items():
            for att, tls in atts.items():
                for tl in list(tls):
                    spec = fmt.DEFORM_TIMELINE if tl == "deform" else fmt.SEQUENCE_TIMELINE
                    yield tl, f"{skin}/{slot}/{att}", None, tls, tl, spec
    if anim.get("drawOrder"):
        yield "drawOrder", None, None, anim, "drawOrder", fmt.SEQUENCE_TIMELINE
    for folder in anim.get("drawOrderFolder") or []:
        if folder.get("keys"):
            yield "drawOrder", None, None, folder, "keys", fmt.SEQUENCE_TIMELINE
    if anim.get("events"):
        yield "events", None, None, anim, "events", None


def _is_deform(spec: fmt.TimelineSpec) -> bool:
    return spec.values == ("__blend",)


def _vertices(k: dict, n: int = 0) -> list[float]:
    """A deform key's vertex offsets as a full array (leading `offset`
    zeros), padded to n."""
    out = [0.0] * int(k.get("offset", 0)) + [float(v) for v in k.get("vertices") or []]
    return out + [0.0] * (n - len(out))


def _pose_of(spec: fmt.TimelineSpec, k: dict) -> list[float]:
    return _vertices(k) if _is_deform(spec) else key_values(spec, k)


def _value_fields(spec: fmt.TimelineSpec, values: list[float]) -> dict:
    """Key fields holding `values` (the inverse of key_values)."""
    if spec.kind == "color":
        out, i = {}, 0
        for fld, n in spec.color_fields:
            out[fld] = "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in values[i:i + n])
            i += n
        return out
    return {name: _r(v) for name, v in zip(spec.values, values)}


def _key_between(spec: fmt.TimelineSpec, k: dict, nxt: dict, t: float) -> tuple[Any, dict]:
    """Cut the segment k -> nxt at time t, keeping its shape: (curve of k up
    to the new key, the new key with its curve to nxt)."""
    t1, t2 = key_time(k), key_time(nxt)
    curve = k.get("curve")
    new = {kk: vv for kk, vv in k.items() if kk != "curve"}
    new["time"] = t
    if _is_deform(spec):
        if curve == "stepped":
            blend, left, right = 0.0, "stepped", "stepped"
        elif isinstance(curve, list):
            blend, lc, rc = split_bezier(t, t1, 0.0, curve[0], curve[1], curve[2], curve[3], t2, 1.0)
            if 1e-6 < blend < 1 - 1e-6:
                left = [lc[0], lc[1] / blend, lc[2], lc[3] / blend]
                right = [rc[0], (rc[1] - blend) / (1 - blend), rc[2], (rc[3] - blend) / (1 - blend)]
            else:
                left = right = None
        else:
            blend, left, right = (t - t1) / (t2 - t1), None, None
        n = max(len(_vertices(k)), len(_vertices(nxt)))
        a, b = _vertices(k, n), _vertices(nxt, n)
        new.pop("offset", None)
        new.pop("vertices", None)
        verts = [_r(x + (y - x) * blend) for x, y in zip(a, b)]
        if any(verts):
            new["vertices"] = verts
    else:
        v1, v2 = key_values(spec, k), key_values(spec, nxt)
        if curve == "stepped":
            vals, left, right = v1, "stepped", "stepped"
        elif isinstance(curve, list) and len(curve) == 4 * len(v1):
            vals, left, right = [], [], []
            for j, (x, y) in enumerate(zip(v1, v2)):
                v, lc, rc = split_bezier(t, t1, x, *curve[j * 4:j * 4 + 4], t2, y)
                vals.append(v)
                left += lc
                right += rc
        else:
            a = (t - t1) / (t2 - t1)
            vals, left, right = [x + (y - x) * a for x, y in zip(v1, v2)], None, None
        new.update(_value_fields(spec, vals))
    if right is not None:
        new["curve"] = right
    return left, new


def with_key_at(spec: fmt.TimelineSpec, keys: list[dict], t: float) -> list[dict]:
    """The same curve timeline with a key at time t (inserted on the curve,
    or a hold before the first / after the last key)."""
    keys = [dict(k) for k in keys]
    if any(abs(key_time(k) - t) < 1e-6 for k in keys):
        return keys
    if t < key_time(keys[0]):
        hold = {kk: vv for kk, vv in keys[0].items() if kk != "curve"}
        hold["time"] = t
        return [hold, *keys]
    if t > key_time(keys[-1]):
        hold = {kk: vv for kk, vv in keys[-1].items() if kk != "curve"}
        hold["time"] = t
        return [*keys, hold]
    i = max(j for j, k in enumerate(keys) if key_time(k) < t)
    left, new = _key_between(spec, keys[i], keys[i + 1], t)
    keys[i].pop("curve", None)
    if left is not None:
        keys[i]["curve"] = left
    return [*keys[:i + 1], new, *keys[i + 1:]]


def _moved(k: dict, delta: float) -> dict:
    out = dict(k)
    out["time"] = key_time(k) + delta
    if isinstance(k.get("curve"), list):
        out["curve"] = [v + delta if i % 2 == 0 else v for i, v in enumerate(k["curve"])]
    return out


def _tidy_all(keys: list[dict]) -> list[dict]:
    out = []
    for k in keys:
        k = dict(k)
        if isinstance(k.get("curve"), list):
            k["curve"] = [_r(v) for v in k["curve"]]
        if not k.get("time") or abs(k["time"]) < 1e-6:
            k.pop("time", None)
        out.append(_tidy_key(k))
    return out


def shift_keys(
    keys: list[dict], spec: fmt.TimelineSpec | None, offset: float, duration: float,
    wrap: bool = True,
) -> list[dict]:
    """Move a timeline in time by `offset` seconds.

    wrap=True treats it as a loop of length `duration`: what leaves at the
    end comes back at the start, the curve is cut exactly at the loop point
    (same motion, new phase). This is how overlapping action is made: the
    forearm repeats the arm's motion a few frames later. A curve timeline
    must loop (first key = last key) to be wrapped. spec None = events."""
    if not keys:
        return keys
    if not wrap:
        if min(key_time(k) for k in keys) + offset < -1e-9:
            raise AnimationError("offset would move keys before 0 (use wrap=true on a loop)")
        return _tidy_all([_moved(k, offset) for k in keys])
    if duration <= 0:
        raise AnimationError("wrap needs a loop duration > 0")
    d = offset % duration
    if d < 1e-6 or duration - d < 1e-6:
        return keys
    if max(key_time(k) for k in keys) > duration + 1e-6:
        raise AnimationError("timeline is longer than the loop duration")
    if spec is None or not spec.curve:
        # Events fire at their new time; stepped keys also need the state that
        # is active across the loop point at time 0.
        by_time = {round((key_time(k) + d) % duration, 6): {**k, "time": (key_time(k) + d) % duration}
                   for k in keys}
        out = [by_time[t] for t in sorted(by_time)]
        if spec is not None and key_time(out[0]) > 1e-6:
            out.insert(0, {**out[-1], "time": 0})
        return _tidy_all(out)
    ks = with_key_at(spec, with_key_at(spec, keys, 0.0), duration)
    a, b = _pose_of(spec, ks[0]), _pose_of(spec, ks[-1])
    n = max(len(a), len(b))
    if any(abs(x - y) > 1e-3 for x, y in zip(a + [0.0] * (n - len(a)), b + [0.0] * (n - len(b)))):
        raise AnimationError("timeline does not loop (first and last key differ): "
                             "make them equal or pass wrap=false")
    cut = duration - d
    ks = with_key_at(spec, ks, cut)
    head = [k for k in ks if key_time(k) < cut - 1e-6]
    tail = [k for k in ks if key_time(k) >= cut - 1e-6]
    end = {kk: vv for kk, vv in tail[0].items() if kk != "curve"}
    end["time"] = duration
    return _tidy_all([*(_moved(k, -cut) for k in tail[:-1]), *(_moved(k, d) for k in head), end])


def scale_values(spec: fmt.TimelineSpec, keys: list[dict], factor: float, pivot: float | None = None) -> list[dict]:
    """Amplify (factor > 1) or soften (< 1) a numeric timeline around `pivot`
    (default: the timeline's neutral value, 0 for offsets and 1 for scale).
    Curves keep their shape."""
    if spec.kind != "num" or not spec.curve or _is_deform(spec):
        raise AnimationError("only numeric curve timelines can be scaled")
    out = []
    for k in keys:
        k = dict(k)
        for j, (name, default) in enumerate(zip(spec.values, spec.defaults)):
            p = default if pivot is None else pivot
            if name in k or p != default:
                k[name] = _r(p + (float(k.get(name, default)) - p) * factor)
            if isinstance(k.get("curve"), list) and len(k["curve"]) == 4 * len(spec.values):
                c = list(k["curve"])
                for i in (j * 4 + 1, j * 4 + 3):
                    c[i] = _r(p + (c[i] - p) * factor)
                k["curve"] = c
        out.append(k)
    return out


# ------------------------------------------------------------- sampling
def sample(spec: fmt.TimelineSpec, keys: list[dict], time: float) -> list[float] | None:
    """Values of a curve timeline at `time`, or None before the first key
    (the runtime then uses the setup pose)."""
    if not keys or time < key_time(keys[0]):
        return None
    for i in range(len(keys) - 1, -1, -1):
        if time >= key_time(keys[i]):
            break
    k = keys[i]
    v1 = key_values(spec, k)
    if i == len(keys) - 1:
        return v1
    nxt = keys[i + 1]
    v2 = key_values(spec, nxt)
    t1, t2 = key_time(k), key_time(nxt)
    curve = k.get("curve")
    if curve == "stepped":
        return v1
    if t2 <= t1:
        return v2
    if curve is None:
        a = (time - t1) / (t2 - t1)
        return [x + (y - x) * a for x, y in zip(v1, v2)]
    out = []
    for j, (x, y) in enumerate(zip(v1, v2)):
        cx1, cy1, cx2, cy2 = curve[j * 4 : j * 4 + 4]
        out.append(bezier_value(time, t1, x, cx1, cy1, cx2, cy2, t2, y))
    return out


def sample_stepped(keys: list[dict], time: float) -> dict | None:
    """Last key at or before `time` (attachment, inherit, sequence...)."""
    found = None
    for k in keys or []:
        if key_time(k) <= time:
            found = k
        else:
            break
    return found


def deform_blend(keys: list[dict], time: float) -> tuple[dict, dict | None, float] | None:
    """For deform timelines: (key, next_key, blend 0..1) at time."""
    if not keys or time < key_time(keys[0]):
        return None
    for i in range(len(keys) - 1, -1, -1):
        if time >= key_time(keys[i]):
            break
    k = keys[i]
    if i == len(keys) - 1:
        return k, None, 0.0
    nxt = keys[i + 1]
    t1, t2 = key_time(k), key_time(nxt)
    curve = k.get("curve")
    if curve == "stepped" or t2 <= t1:
        return k, nxt, 0.0
    if curve is None:
        return k, nxt, (time - t1) / (t2 - t1)
    cx1, cy1, cx2, cy2 = curve[0:4]
    return k, nxt, bezier_value(time, t1, 0.0, cx1, cy1, cx2, cy2, t2, 1.0)
