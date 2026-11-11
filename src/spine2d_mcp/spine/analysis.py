"""Animation quality checks: what an animation lead would circle in review.

Two sources:

- `analyze()` reads the keys (pure Python): loop seams, linear (mechanical)
  segments, dead keys under an IK constraint, twinning, chains without
  overlapping action, squash without volume, baked key soup...
- `motion_report()` reads bone world transforms sampled from the official
  runtime (constraints and physics applied): pops, loop gap as the game will
  show it, dead holds, foot contacts and ground speed.

Every finding is {"severity", "code", "where", "message", "fix"}; `fix` names
the tool call that addresses it. The checks are heuristics: they point at
what to LOOK at in a render, they do not replace looking.
"""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

from . import animation as an
from . import document as doc
from . import format as fmt

SEVERITIES = ("error", "warning", "info")


def _issue(severity: str, code: str, where: str, message: str, fix: str = "") -> dict:
    out = {"severity": severity, "code": code, "where": where, "message": message}
    if fix:
        out["fix"] = fix
    return out


def _num(v: float) -> float:
    return round(float(v), 3)


def _curve_timelines(anim: dict):
    """(label, kind, target, timeline, spec, keys) for value timelines."""
    for kind, target, tl, container, key, spec in an.iter_timelines(anim):
        if spec is None or not spec.curve or spec.values == ("__blend",):
            continue
        label = ".".join(x for x in (kind if kind != "bone" else "", target, tl) if x)
        yield label, kind, target, tl, spec, container[key]


def looks_like_loop(anim: dict) -> bool:
    """True when most value timelines end on the pose they start with."""
    same = total = 0
    for _, _, _, _, spec, keys in _curve_timelines(anim):
        if len(keys) < 2:
            continue
        total += 1
        a, b = an.key_values(spec, keys[0]), an.key_values(spec, keys[-1])
        same += all(abs(x - y) <= 1e-3 * max(1.0, abs(x)) for x, y in zip(a, b))
    return total > 0 and same >= 0.8 * total


_SIDES = (
    (re.compile(r"left", re.I), "right"), (re.compile(r"front"), "rear"),
    (re.compile(r"(?<=[_\-. ])l$", re.I), "r"), (re.compile(r"^l(?=[_\-. ])", re.I), "r"),
)


def _other_side(name: str) -> str | None:
    for pattern, repl in _SIDES:
        if pattern.search(name):
            return pattern.sub(lambda m: repl.upper() if m.group(0).isupper() else repl, name)
    return None


def _times(keys: list[dict]) -> tuple[float, ...]:
    return tuple(round(an.key_time(k), 4) for k in keys)


def _span(spec: fmt.TimelineSpec, keys: list[dict]) -> float:
    vals = [an.key_values(spec, k) for k in keys]
    return max((max(col) - min(col) for col in zip(*vals)), default=0.0)


def analyze(data: dict, name: str, loop: bool | None = None) -> dict:
    """Key-level review of one animation."""
    anim = doc.animations(data).get(name)
    if anim is None:
        raise ValueError(f"animation {name!r} not found")
    duration = an.animation_duration(anim)
    issues: list[dict] = []
    auto = loop is None
    if auto:
        loop = looks_like_loop(anim)
    timelines = list(_curve_timelines(anim))
    key_count = sum(len(c[k]) for _, _, _, c, k, _ in an.iter_timelines(anim))
    if duration <= 0:
        issues.append(_issue("warning", "empty", name, "the animation has no duration (no key after time 0)"))

    # ---- loop seam -------------------------------------------------------
    if loop and duration > 0:
        for label, kind, _, _, spec, keys in timelines:
            if an.key_time(keys[0]) > 1e-6 and kind != "bone":
                continue  # before its first key the value is the setup pose, unknown here
            start = an.sample(spec, keys, 0.0) or list(spec.defaults)
            end = an.sample(spec, keys, duration)
            span = max(_span(spec, keys), 1e-6)
            gap = max(abs(a - b) for a, b in zip(start, end))
            if gap > max(0.02 * span, 1e-3):
                issues.append(_issue(
                    "warning", "loop_pop", label,
                    f"the value at the end ({_num(max(end, key=abs))}) differs from the start by "
                    f"{_num(gap)}: the loop jumps",
                    "set the last key equal to the first (set_keyframes at the animation's duration)"))
                continue
            if len(keys) < 3 or duration < 0.1:
                continue
            h = duration * 1e-3
            v0 = [(b - a) / h for a, b in zip(start, an.sample(spec, keys, h) or start)]
            v1 = [(b - a) / h for a, b in zip(an.sample(spec, keys, duration - h) or end, end)]
            peak = 0.0
            steps = 48
            prev = start
            for i in range(1, steps + 1):
                cur = an.sample(spec, keys, duration * i / steps) or prev
                peak = max(peak, max(abs(b - a) for a, b in zip(prev, cur)) * steps / duration)
                prev = cur
            jump = max(abs(a - b) for a, b in zip(v0, v1))
            if peak > 0 and jump > 0.5 * peak:
                issues.append(_issue(
                    "info", "loop_hitch", label,
                    f"speed changes abruptly at the loop point ({_num(max(v1, key=abs))}/s -> "
                    f"{_num(max(v0, key=abs))}/s): visible as a tick every cycle",
                    "give the last segment and the first segment matching tangents (curve), "
                    "or move the seam with offset_keys(wrap=true)"))

    # ---- interpolation ---------------------------------------------------
    bones_anim = anim.get("bones") or {}
    linear = moving = stepped = 0
    linear_where: list[str] = []
    for label, kind, _, tl, spec, keys in timelines:
        if kind != "bone":
            continue
        n_lin = 0
        for k, nxt in zip(keys, keys[1:]):
            if an.key_values(spec, k) == an.key_values(spec, nxt):
                continue
            moving += 1
            if k.get("curve") is None:
                n_lin += 1
            elif k.get("curve") == "stepped":
                stepped += 1
        linear += n_lin
        if n_lin:
            linear_where.append(f"{label} ({n_lin})")
    if linear >= 3 and linear > 0.5 * moving:
        issues.append(_issue(
            "warning", "linear_motion", ", ".join(linear_where[:8]),
            f"{linear} of {moving} moving segments are linear: constant speed, no ease in / out, "
            "reads as mechanical",
            'add "curve" to the keys (set_keyframes mode="merge"): easeOut after an impact or a fast '
            "start, easeIn into a hit, easeInOut for settles, easeOutBack for overshoot"))
    if stepped >= 3 and stepped > 0.5 * moving:
        issues.append(_issue(
            "info", "stepped_motion", name,
            f"{stepped} of {moving} moving segments are stepped (pose-to-pose blocking)",
            "replace the stepped curves with eased ones once the poses are approved"))

    # ---- dead keys under IK ---------------------------------------------
    ik_anim = anim.get("ik") or {}
    for c in data.get("constraints") or []:
        if c.get("type") != "ik" or float(c.get("mix", 1)) < 1:
            continue
        if any(float(k.get("mix", 1)) < 1 for k in ik_anim.get(c["name"]) or []):
            continue
        dead = [b for b in c.get("bones") or [] if (bones_anim.get(b) or {}).get("rotate")]
        if dead:
            issues.append(_issue(
                "warning", "dead_keys", ", ".join(f"{b}.rotate" for b in dead),
                f"IK constraint {c['name']!r} (mix 1) overrides these rotations: the keys do nothing",
                f"key the IK target {c['target']!r} (translate) instead, or key the IK mix to 0 "
                "(set_keyframes kind=\"ik\") for an FK section"))

    # ---- twinning --------------------------------------------------------
    seen: set[str] = set()
    for bone, tls in bones_anim.items():
        other = _other_side(bone)
        if not other or other not in bones_anim or bone in seen:
            continue
        seen.add(other)
        for tl in ("rotate", "translate"):
            a, b = (tls or {}).get(tl), (bones_anim[other] or {}).get(tl)
            if not a or not b or len(a) < 3:
                continue
            spec = fmt.BONE_TIMELINES[tl]
            if _times(a) == _times(b) and [an.key_values(spec, k) for k in a] == [an.key_values(spec, k) for k in b] \
                    and _span(spec, a) > 0:
                issues.append(_issue(
                    "info", "twinning", f"{bone}.{tl} = {other}.{tl}",
                    "both sides do exactly the same thing on the same frames (twinning): looks robotic "
                    "unless it is a deliberate symmetric action",
                    f'offset_keys(bones=["{other}"], offset=0.03 to 0.1) and vary one side slightly '
                    "(scale_keys factor 0.85)"))

    # ---- chains without overlap -----------------------------------------
    parent = {b["name"]: b.get("parent") for b in doc.bones(data)}
    keyed = {b for b, tls in bones_anim.items() if len((tls or {}).get("rotate") or []) >= 3}
    for head in sorted(b for b in keyed if parent.get(b) not in keyed):
        chain = [head]
        while True:
            kids = [b for b in keyed if parent.get(b) == chain[-1]]
            if len(kids) != 1:
                break
            chain.append(kids[0])
        if len(chain) >= 3 and len({_times(bones_anim[b]["rotate"]) for b in chain}) == 1:
            issues.append(_issue(
                "info", "no_overlap", " > ".join(chain),
                "every bone of the chain is keyed on the same frames: the whole limb moves as one "
                "rigid piece (no overlapping action / drag)",
                f"offset_keys(bones={chain!r}, offset=0, stagger=0.03 to 0.07) so each bone "
                "follows its parent a few frames later"))

    # ---- squash without volume, spins, key soup --------------------------
    for label, kind, _, tl, spec, keys in timelines:
        if kind == "bone" and tl == "scale":
            bad = [k for k in keys
                   if (float(k.get("x", 1)) - 1) * (float(k.get("y", 1)) - 1) < 0
                   and abs(float(k.get("x", 1)) * float(k.get("y", 1)) - 1) > 0.15]
            if bad:
                k = bad[0]
                issues.append(_issue(
                    "info", "squash_volume", label,
                    f"squash & stretch does not keep the volume at t={_num(an.key_time(k))} "
                    f"(x*y = {_num(float(k.get('x', 1)) * float(k.get('y', 1)))}): the shape seems to "
                    "inflate or shrink",
                    "use y = 1/x (x 1.2 -> y 0.83)"))
        if kind == "bone" and tl == "rotate":
            for k, nxt in zip(keys, keys[1:]):
                turn = float(nxt.get("value", 0)) - float(k.get("value", 0))
                if abs(turn) > 180:
                    issues.append(_issue(
                        "info", "spin", label,
                        f"turns {_num(turn)} deg between t={_num(an.key_time(k))} and "
                        f"t={_num(an.key_time(nxt))} (more than half a turn): is the spin intended?"))
                    break
        span_t = an.key_time(keys[-1]) - an.key_time(keys[0])
        if len(keys) > 40 and span_t > 0 and len(keys) / span_t > 20:
            issues.append(_issue(
                "info", "key_soup", label,
                f"{len(keys)} keys ({_num(len(keys) / span_t)}/s): baked motion is heavy and hard to edit",
                "fewer keys with bezier curves, or spine_clean_up on the project"))

    counts = {s: sum(1 for i in issues if i["severity"] == s) for s in SEVERITIES}
    return {
        "animation": name,
        "duration": _num(duration),
        "loop": {"assumed": bool(loop), "auto_detected": auto},
        "keys": key_count,
        "timelines": sum(1 for _ in an.iter_timelines(anim)),
        "bones_keyed": len(bones_anim),
        "events": len(anim.get("events") or []),
        "issues": issues,
        "counts": counts,
    }


# --------------------------------------------------------------- runtime
def _speeds(xs: list[float], ys: list[float]) -> list[float]:
    return [math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(len(xs) - 1)]


def motion_report(
    sampled: dict, loop: bool, physics_bones: set[str] | None = None,
    ground_bones: list[str] | None = None,
) -> dict:
    """Review of the motion the runtime really produces. `sampled` is the
    result of runtime.render.sample(loop=False, include_last=True)."""
    times: list[float] = sampled["times"]
    tracks: dict[str, dict[str, list[float]]] = sampled["tracks"]
    issues: list[dict] = []
    if len(times) < 3 or not tracks:
        return {"issues": issues}
    dt = (times[-1] - times[0]) / (len(times) - 1)
    xs = [v for tr in tracks.values() for v in tr["x"]]
    ys = [v for tr in tracks.values() for v in tr["y"]]
    size = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1e-6)
    physics_bones = physics_bones or set()

    speeds = {b: _speeds(tr["x"], tr["y"]) for b, tr in tracks.items()}
    travel = {b: sum(s) for b, s in speeds.items()}
    moving = [b for b, t in travel.items() if t > 0.002 * size]

    # Loop gap: last pose vs first pose, as the game shows it at the wrap.
    if loop:
        gaps = []
        for b, tr in tracks.items():
            if b in physics_bones:
                continue
            d = math.hypot(tr["x"][-1] - tr["x"][0], tr["y"][-1] - tr["y"][0])
            r = abs((tr["rotation"][-1] - tr["rotation"][0] + 180) % 360 - 180)
            if d > 0.004 * size or r > 1.0:
                gaps.append((d, r, b))
        if gaps:
            gaps.sort(reverse=True)
            top = ", ".join(f"{b} ({_num(d)} units, {_num(r)} deg)" for d, r, b in gaps[:5])
            issues.append(_issue(
                "warning", "loop_gap", top,
                f"{len(gaps)} bone(s) end the cycle away from where they start: a visible jump "
                "every loop",
                "make the pose at the last frame equal to the first (same keys at 0 and at the "
                "duration, on the IK targets too)"))

    # Pops: one frame much faster than its neighbours and than the rest.
    pops = []
    for b, s in speeds.items():
        nz = sorted(v for v in s if v > 1e-6)
        if len(nz) < 4:
            continue
        typical = median(nz)
        for i in range(1, len(s) - 1):
            if s[i] > 6 * typical and s[i] > 0.03 * size and s[i - 1] < s[i] / 3 and s[i + 1] < s[i] / 3:
                pops.append((s[i], b, times[i + 1]))
    if pops:
        pops.sort(reverse=True)
        issues.append(_issue(
            "warning", "pop", ", ".join(f"{b} at t={_num(t)}" for _, b, t in pops[:5]),
            "the bone jumps in a single frame (a pop): a missing or misplaced key, an IK flip, or a "
            "stepped curve",
            "render a sheet around that time (runtime_render times=[...]) and smooth the keys"))

    # Dead holds: nothing moves at all.
    frame_max = [max((speeds[b][i] for b in speeds), default=0.0) for i in range(len(times) - 1)]
    best = cur = 0
    end_i = 0
    for i, v in enumerate(frame_max):
        cur = cur + 1 if v < 0.0005 * size else 0
        if cur > best:
            best, end_i = cur, i
    hold = best * dt
    total = times[-1] - times[0]
    if moving and hold >= 0.25 and hold >= 0.2 * total:
        t1 = times[end_i + 1]
        issues.append(_issue(
            "info", "dead_hold", f"t={_num(t1 - hold)} to t={_num(t1)}",
            f"nothing moves for {_num(hold)} s: a frozen frame looks dead on screen",
            "keep a moving hold (a few percent of drift, breathing or settle with easeOut), or a "
            "physics constraint on hair / cloth"))

    out: dict[str, Any] = {
        "issues": issues,
        "sampled_frames": len(times),
        "moving_bones": len(moving),
        "static_bones": len(tracks) - len(moving),
        "most_active": [{"bone": b, "travel": _num(travel[b])}
                        for b in sorted(travel, key=travel.get, reverse=True)[:5] if travel[b] > 0],
        "peak_speed": _num(max((max(s) for s in speeds.values() if s), default=0.0) / dt),
    }

    # Ground contact: where the feet touch, and how fast the ground must move.
    if ground_bones:
        contacts = []
        ground_speeds = []
        for b in ground_bones:
            if b not in tracks:
                raise ValueError(f"ground bone {b!r} not found")
            tr = tracks[b]
            floor = min(tr["y"])
            tol = max(0.06 * (max(tr["y"]) - floor), 0.002 * size)
            down = [y <= floor + tol for y in tr["y"]]
            i = 0
            while i < len(down):
                if not down[i]:
                    i += 1
                    continue
                j = i
                while j + 1 < len(down) and down[j + 1]:
                    j += 1
                if j - i >= 2:
                    vx = [(tr["x"][k + 1] - tr["x"][k]) / dt for k in range(i, j)]
                    # The first / last frames of a contact are the landing and
                    # the lift: judge the speed on the middle of the stance.
                    edge = max(1, round(0.12 * len(vx))) if len(vx) >= 5 else 0
                    vx = vx[edge:len(vx) - edge]
                    mean = median(vx)
                    dev = math.sqrt(sum((v - mean) ** 2 for v in vx) / len(vx))
                    contacts.append({"bone": b, "from": _num(times[i]), "to": _num(times[j]),
                                     "ground_speed": _num(abs(mean))})
                    ground_speeds.append(abs(mean))
                    if abs(mean) > 0.02 * size and dev > 0.2 * abs(mean):
                        issues.append(_issue(
                            "warning", "foot_slide", f"{b} t={_num(times[i])}-{_num(times[j])}",
                            f"the foot's speed on the ground varies by {_num(100 * dev / abs(mean))} %: "
                            "it skates when the game moves the character at a constant speed",
                            "key the stance of the IK target with LINEAR interpolation between contact "
                            'and toe-off (or generate_animation preset "walk" on an IK rig)'))
                i = j + 1
        out["contacts"] = contacts
        if ground_speeds:
            out["ground_speed"] = _num(sum(ground_speeds) / len(ground_speeds))
    return out
