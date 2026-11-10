"""Procedural animation generators.

Everything here writes ordinary Spine keys with bezier curves (no baking at
fps), so the result stays light and fully editable in the Spine editor.

The core primitive is `function_keys`: given a smooth function f(t), its
derivative and the key times, it emits keys whose bezier handles are the
Hermite tangents of f, which reproduces sines, damped oscillations, arcs... very
closely with few keys. On top of it:

- `oscillate`: sine motion on any bone timeline (loops seamlessly when the
  duration is a multiple of the period), with phase for overlapping action.
- `follow_through`: the same oscillation propagated down a bone chain with a
  per-bone delay and amplitude falloff (tails, hair, capes, tentacles).
- Character presets for humanoid rigs (the PSD importer's bone names, or any
  rig through a role -> bone mapping): idle/breathing, walk, run, jump, wave,
  nod, head shake, blink, hover, bounce with squash & stretch, shake/hit,
  flash/fade/pulse on slot colors.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Sequence

from . import document as doc
from . import format as fmt
from .animation import AnimationError, sample, set_draw_order_keys, set_keys

Fn = Callable[[float], float]


def _r(v: float) -> float:
    v = round(v, 5)
    return 0.0 if v == 0 else v


def function_keys(
    f: Fn,
    df: Fn,
    times: Sequence[float],
    field: str = "value",
) -> list[dict]:
    """Keys at `times` with Hermite-derived bezier curves for f."""
    times = sorted(set(round(t, 6) for t in times))
    keys = []
    for i, t in enumerate(times):
        k: dict = {"time": t, field: _r(f(t))}
        if i + 1 < len(times):
            t2 = times[i + 1]
            dt = t2 - t
            k["curve"] = {
                "raw": [
                    _r(t + dt / 3), _r(f(t) + df(t) * dt / 3),
                    _r(t2 - dt / 3), _r(f(t2) - df(t2) * dt / 3),
                ]
            }
        keys.append(k)
    return keys


def function_keys_xy(
    fx: Fn, dfx: Fn, fy: Fn, dfy: Fn, times: Sequence[float]
) -> list[dict]:
    """Same for two-value timelines (translate, scale, shear)."""
    times = sorted(set(round(t, 6) for t in times))
    keys = []
    for i, t in enumerate(times):
        k: dict = {"time": t, "x": _r(fx(t)), "y": _r(fy(t))}
        if i + 1 < len(times):
            t2 = times[i + 1]
            dt = t2 - t
            raw = []
            for f, df in ((fx, dfx), (fy, dfy)):
                raw += [
                    _r(t + dt / 3), _r(f(t) + df(t) * dt / 3),
                    _r(t2 - dt / 3), _r(f(t2) - df(t2) * dt / 3),
                ]
            k["curve"] = {"raw": raw}
        keys.append(k)
    return keys


def _sine(base: float, amp: float, period: float, phase_deg: float) -> tuple[Fn, Fn]:
    w = 2 * math.pi / period
    ph = math.radians(phase_deg)
    return (
        lambda t: base + amp * math.sin(w * t + ph),
        lambda t: amp * w * math.cos(w * t + ph),
    )


def _extreme_times(period: float, phase_deg: float, duration: float) -> list[float]:
    """Times of the sine's peaks/troughs in [0, duration] plus both ends."""
    ph = math.radians(phase_deg)
    w = 2 * math.pi / period
    times = [0.0, duration]
    k = math.ceil(((-ph) + math.pi / 2) / math.pi - 1e-9) - 2
    while True:
        t = (math.pi / 2 + k * math.pi - ph) / w
        k += 1
        if t > duration + 1e-9:
            break
        if t > 1e-6:
            times.append(t)
    return times


def _anim(data: dict, name: str, mode: str) -> dict:
    anims = doc.animations(data)
    if mode == "replace" or name not in anims:
        anims[name] = {}
    return anims[name]


def oscillate(
    data: dict,
    animation: str,
    bone: str,
    timeline: str = "rotate",
    amplitude: float = 10.0,
    period: float = 1.0,
    duration: float | None = None,
    phase: float = 0.0,
    base: float | None = None,
    axis: str = "both",
    mode: str = "merge",
    start: float = 0.0,
) -> list[dict]:
    """Sine oscillation on a bone timeline.

    timeline: rotate, translatex/y, scalex/y, shearx/y (1 value) or
    translate/scale/shear (2 values; `axis` x, y or both). `base` is the
    center value (default: 0 for offsets, 1 for scale). Phase in degrees.
    `start` delays the oscillation (keys from `start` to `start + duration`)."""
    doc.find_bone(data, bone)
    duration = duration or period
    anim = doc.animations(data).setdefault(animation, {})
    times = [start + t for t in _extreme_times(period, phase, duration)]
    is_scale = timeline.startswith("scale")
    b = (1.0 if is_scale else 0.0) if base is None else base
    f0, df0 = _sine(b, amplitude, period, phase)
    f = lambda t: f0(t - start)  # noqa: E731
    df = lambda t: df0(t - start)  # noqa: E731
    if timeline in ("translate", "scale", "shear"):
        const, zero = (lambda t: b), (lambda t: 0.0)
        fx, dfx = (f, df) if axis in ("x", "both") else (const, zero)
        fy, dfy = (f, df) if axis in ("y", "both") else (const, zero)
        keys = function_keys_xy(fx, dfx, fy, dfy, times)
    else:
        keys = function_keys(f, df, times)
    return set_keys(anim, "bone", bone, timeline, keys, mode=mode)


def follow_through(
    data: dict,
    animation: str,
    bones: Sequence[str],
    amplitude: float = 15.0,
    period: float = 1.0,
    duration: float | None = None,
    delay: float = 40.0,
    falloff: float = 0.0,
    timeline: str = "rotate",
    mode: str = "merge",
) -> None:
    """Wave principle / overlapping action: each bone of the chain repeats the
    oscillation `delay` degrees of phase later (and `falloff`% larger or
    smaller amplitude) than its parent."""
    for i, b in enumerate(bones):
        oscillate(
            data, animation, b, timeline,
            amplitude=amplitude * (1 + falloff / 100.0) ** i,
            period=period, duration=duration, phase=-delay * i, mode=mode,
        )


# ------------------------------------------------------------ humanoid rig
ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "root": ("root",),
    "hip": ("hip", "hips", "pelvis"),
    "torso": ("torso", "body", "spine"),
    "chest": ("chest", "torso2", "spine2"),
    "neck": ("neck",),
    "head": ("head",),
    "arm_left": ("arm_left", "upper_arm_left", "left_arm", "front-upper-arm", "arm_l"),
    "arm_right": ("arm_right", "upper_arm_right", "right_arm", "rear-upper-arm", "arm_r"),
    "forearm_left": ("forearm_left", "lower_arm_left", "front-bracer", "forearm_l"),
    "forearm_right": ("forearm_right", "lower_arm_right", "rear-bracer", "forearm_r"),
    "hand_left": ("hand_left", "left_hand", "front-fist", "hand_l"),
    "hand_right": ("hand_right", "right_hand", "rear-fist", "hand_r"),
    "leg_left": ("leg_left", "thigh_left", "left_leg", "front-thigh", "thigh_l"),
    "leg_right": ("leg_right", "thigh_right", "right_leg", "rear-thigh", "thigh_r"),
    "shin_left": ("shin_left", "calf_left", "front-shin", "shin_l"),
    "shin_right": ("shin_right", "calf_right", "rear-shin", "shin_r"),
    "foot_left": ("foot_left", "left_foot", "front-foot", "foot_l"),
    "foot_right": ("foot_right", "right_foot", "rear-foot", "foot_r"),
    "eye_left": ("eye_left", "left_eye", "eye_l"),
    "eye_right": ("eye_right", "right_eye", "eye_r"),
    "eyes": ("eyes", "eye"),
    "tail": ("tail", "tail1"),
}


def resolve_roles(data: dict, overrides: dict[str, str] | None = None) -> dict[str, str]:
    names = {b["name"] for b in doc.bones(data)}
    lower = {n.lower(): n for n in names}
    roles: dict[str, str] = {}
    for role, cands in ROLE_CANDIDATES.items():
        for c in cands:
            if c.lower() in lower:
                roles[role] = lower[c.lower()]
                break
    for role, bone in (overrides or {}).items():
        if bone not in names:
            raise AnimationError(f"role {role!r} mapped to missing bone {bone!r}")
        roles[role] = bone
    return roles


def _cycle(
    data: dict, name: str, plan: list[tuple[str, str, float, float, float, float]],
    period: float, duration: float, roles: dict[str, str],
) -> list[str]:
    """plan: (role, timeline, amplitude, phase_deg, frequency_mult, base)."""
    used = []
    for role, tl, amp, phase, freq, base in plan:
        bone = roles.get(role)
        if bone is None or amp == 0:
            continue
        oscillate(data, name, bone, tl, amplitude=amp, period=period / freq,
                  duration=duration, phase=phase, base=base if base == base else None)
        used.append(f"{bone}.{tl}")
    return used


NAN = float("nan")


# ------------------------------------------------------------ IK-aware rigs
# An IK constraint at full mix overrides the rotation of its chain bones, so
# FK rotate keys on a leg / arm driven by IK do nothing: the limb stays still
# while the body moves. The presets therefore animate the IK TARGET of such a
# chain (planted feet for walk / run, FK motion re-expressed on the target
# everywhere else) and leave no dead rotate keys behind.


def ik_constraint_of(data: dict, bone: str | None) -> dict | None:
    """The IK constraint (mix > 0) whose chain contains `bone`."""
    if bone is None:
        return None
    for c in data.get("constraints") or []:
        if c.get("type") == "ik" and bone in (c.get("bones") or []) and float(c.get("mix", 1)) > 0:
            return c
    return None


def _chain_geometry(data: dict, con: dict) -> tuple[float, float]:
    """(max reach, setup distance) from the chain's first joint to its IK
    target, in world units."""
    from .pose import Pose

    pose = Pose(data)
    first, target = pose.bones[con["bones"][0]], pose.bones[con["target"]]
    reach = 0.0
    for b in con["bones"]:
        bn = pose.bones[b]
        reach += math.hypot(*(p - q for p, q in zip(bn.tip, (bn.worldX, bn.worldY))))
    return reach, math.hypot(target.worldX - first.worldX, target.worldY - first.worldY)


def _world_to_parent_offset(data: dict, bone: str, dx: float, dy: float) -> tuple[float, float]:
    """A world-space displacement expressed as a translate offset of `bone`
    (translate timelines are in the parent bone's space)."""
    from .pose import Pose

    parent = doc.find_bone(data, bone).get("parent")
    if parent is None:
        return dx, dy
    p = Pose(data).bones[parent]
    det = p.a * p.d - p.b * p.c
    if abs(det) < 1e-12:
        return dx, dy
    return (dx * p.d - dy * p.b) / det, (dy * p.a - dx * p.c) / det


def _hermite_track(
    knots: Sequence[tuple[float, float, float, float, float]], period: float, phase: float,
) -> list[dict]:
    """Looping two-value (x, y) keys from cubic Hermite knots.

    knots: (u, x, y, dx/du, dy/du) with u ascending in [0, 1); the cycle
    wraps from the last knot back to the first. `phase` (0..1) shifts the
    cycle in time; the segment that crosses the loop point is split there so
    the keys run from 0 to `period` and the loop is seamless."""
    n = len(knots)
    pieces: list[tuple[float, float, tuple, tuple]] = []  # (t0, t1, start, end) in cycle units
    for i, k in enumerate(knots):
        nxt = knots[(i + 1) % n]
        u0, u1 = k[0], nxt[0] + (1.0 if i == n - 1 else 0.0)
        pieces.append((u0 + phase, u1 + phase, k[1:], nxt[1:]))

    def at(piece, t: float) -> tuple:
        t0, t1, (x0, y0, mx0, my0), (x1, y1, mx1, my1) = piece
        h = t1 - t0
        s = (t - t0) / h
        h00, h10 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s
        h01, h11 = -2 * s**3 + 3 * s**2, s**3 - s**2
        d00, d10 = 6 * s**2 - 6 * s, 3 * s**2 - 4 * s + 1
        d01, d11 = -6 * s**2 + 6 * s, 3 * s**2 - 2 * s
        return (
            h00 * x0 + h10 * h * mx0 + h01 * x1 + h11 * h * mx1,
            h00 * y0 + h10 * h * my0 + h01 * y1 + h11 * h * my1,
            (d00 * x0 + d01 * x1) / h + d10 * mx0 + d11 * mx1,
            (d00 * y0 + d01 * y1) / h + d10 * my0 + d11 * my1,
        )

    segments: list[tuple[float, float, tuple, tuple]] = []
    for piece in pieces:
        t0, t1 = piece[0], piece[1]
        k = math.floor(t0 + 1e-9)
        t0, t1 = t0 - k, t1 - k
        shifted = (t0, t1, piece[2], piece[3])
        if t1 > 1 + 1e-9:
            mid = at(shifted, 1.0)
            segments.append((t0, 1.0, piece[2], mid))
            segments.append((0.0, t1 - 1.0, mid, piece[3]))
        else:
            segments.append(shifted)
    segments.sort(key=lambda s: s[0])
    keys: list[dict] = []
    for t0, t1, (x0, y0, mx0, my0), (x1, y1, mx1, my1) in segments:
        a, b = t0 * period, t1 * period
        third = (t1 - t0) / 3
        keys.append({"time": _r(a), "x": _r(x0), "y": _r(y0), "curve": {"raw": [
            _r(a + (b - a) / 3), _r(x0 + mx0 * third), _r(b - (b - a) / 3), _r(x1 - mx1 * third),
            _r(a + (b - a) / 3), _r(y0 + my0 * third), _r(b - (b - a) / 3), _r(y1 - my1 * third),
        ]}})
    last = segments[-1]
    keys.append({"time": _r(period), "x": _r(last[3][0]), "y": _r(last[3][1])})
    return keys


def _planted_feet(
    data: dict, name: str, legs: dict[str, dict], duration: float, stride: float,
    bob: float, step_height: float | None, stance: float, facing: int, hip: str | None,
) -> dict:
    """Walk / run feet on IK targets: during the stance the foot slides back
    at constant speed (the ground speed, so it does not skate when the game
    moves the character at `ground_speed`), then lifts and swings forward on
    an arc. The hip is lowered just enough for the legs to reach both
    extremes, so the knees bend instead of the feet leaving their targets."""
    from .pose import Pose

    anim = doc.animations(data)[name]
    reach, rest = min(_chain_geometry(data, c) for c in legs.values())
    # A planted foot reaches out at most a 30 deg leg angle: beyond that the
    # hip would have to sink into a crouch (a run covers the rest in the air).
    half = reach * math.sin(math.radians(min(abs(stride), 30.0)))
    lift = 0.12 * reach if step_height is None else step_height
    speed = 2 * half / stance  # per cycle unit, backwards during the stance
    swing = 1 - stance
    paths: list[tuple[dict, list[dict]]] = []  # (constraint, world-space foot path)
    for side, con in legs.items():
        d = facing
        knots = [
            (0.0, d * half, 0.0, -d * speed, 0.0),                       # contact, foot in front
            (stance, -d * half, 0.0, -d * speed, 0.0),                    # toe-off
            (stance + swing / 2, 0.0, lift, d * 3 * half / swing, 0.0),   # passing, highest
        ]
        world = _hermite_track(knots, duration, 0.25 if side == "left" else 0.75)
        paths.append((con, [{**k, "curve": k["curve"]["raw"]} if "curve" in k else k for k in world]))
        local = []
        for k in world:
            k = dict(k)
            k["x"], k["y"] = (_r(v) for v in _world_to_parent_offset(data, con["target"], k["x"], k["y"]))
            if "curve" in k:
                raw = list(k["curve"]["raw"])
                x1, y1 = _world_to_parent_offset(data, con["target"], raw[1], raw[5])
                x2, y2 = _world_to_parent_offset(data, con["target"], raw[3], raw[7])
                raw[1], raw[5], raw[3], raw[7] = _r(x1), _r(y1), _r(x2), _r(y2)
                k["curve"] = {"raw": raw}
            local.append(k)
        set_keys(anim, "bone", con["target"], "translate", local, mode="replace")
    out = {"targets": sorted(c["target"] for c in legs.values()), "step_length": _r(2 * half),
           "ground_speed": _r(2 * half / (stance * duration))}
    if hip:
        limit = 0.995 * reach
        amp = max(0.0, min(bob, (limit - math.sqrt(max(limit**2 - half**2, 0.0))) / 2))
        # Lowest hip offset needed over the whole cycle for both legs to reach
        # their target (the hip bobs as amp * cos, twice per cycle).
        setup = Pose(data)
        base = 0.0
        for con, path in paths:
            joint, target = setup.bones[con["bones"][0]], setup.bones[con["target"]]
            for i in range(97):
                t = duration * i / 96
                ox, oy = sample(fmt.BONE_TIMELINES["translate"], path, t)
                dx = target.worldX + ox - joint.worldX
                room = math.sqrt(max(limit**2 - dx**2, 0.0)) - (joint.worldY - target.worldY - oy)
                base = min(base, room - amp * math.cos(4 * math.pi * t / duration))
        oscillate(data, name, hip, "translatey", amplitude=amp, period=duration / 2,
                  duration=duration, phase=90, base=base, mode="replace")
        out["hip_drop"] = _r(-base)
    return out


def retarget_fk_to_ik(data: dict, name: str, skip: Sequence[str] = ()) -> list[str]:
    """Re-express FK rotate keys of IK-driven chains on their IK target.

    For every IK constraint (mix > 0, not in `skip`) whose chain bones carry
    rotate keys in animation `name`: the keyed (FK) pose is sampled, the
    position the target would have if it followed the chain is keyed on the
    target's translate timeline (smooth bezier keys), and the dead rotate keys
    are removed. Returns the target bones that were keyed."""
    from .pose import Pose

    anim = doc.animations(data)[name]
    setup = Pose(data)
    done: list[str] = []
    for con in data.get("constraints") or []:
        if con.get("type") != "ik" or con.get("name") in skip or float(con.get("mix", 1)) <= 0:
            continue
        chain, target = con["bones"], con["target"]
        tracks = [(anim.get("bones") or {}).get(b, {}).get("rotate") for b in chain]
        if not any(tracks) or (anim.get("bones") or {}).get(target, {}).get("translate"):
            continue
        times = sorted({round(float(k.get("time", 0)), 6) for keys in tracks if keys for k in keys})
        if len(times) < 2:
            times = [0.0, max(times[0] if times else 0.0, 1e-3)]
        dense = sorted({*times, *((a + b) / 2 for a, b in zip(times, times[1:]))})
        t_setup = setup.bones[target]
        local = setup.bones[chain[-1]].world_to_local(t_setup.worldX, t_setup.worldY)
        parent = doc.find_bone(data, target).get("parent")
        tb = doc.find_bone(data, target)

        cache: dict[float, tuple[float, float]] = {}

        def offset(t: float) -> tuple[float, float]:
            t = min(max(t, dense[0]), dense[-1])
            if t not in cache:
                pose = Pose(data, name, t)
                wx, wy = pose.bones[chain[-1]].local_to_world(*local)
                if parent is not None:
                    wx, wy = pose.bones[parent].world_to_local(wx, wy)
                cache[t] = (wx - float(tb.get("x", 0)), wy - float(tb.get("y", 0)))
            return cache[t]

        h = 1e-3

        def slope(t: float, i: int) -> float:
            a, b = max(t - h, dense[0]), min(t + h, dense[-1])
            return (offset(b)[i] - offset(a)[i]) / (b - a)

        keys = function_keys_xy(lambda t: offset(t)[0], lambda t: slope(t, 0),
                                lambda t: offset(t)[1], lambda t: slope(t, 1), dense)
        for b in chain:
            (anim.get("bones") or {}).get(b, {}).pop("rotate", None)
            if b in (anim.get("bones") or {}) and not anim["bones"][b]:
                del anim["bones"][b]
        set_keys(anim, "bone", target, "translate", keys, mode="replace")
        done.append(target)
    return done


def _ik_legs(data: dict, roles: dict[str, str]) -> dict[str, dict]:
    """side -> IK constraint for the legs driven by IK."""
    out = {}
    for side in ("left", "right"):
        for role in (f"leg_{side}", f"shin_{side}", f"foot_{side}"):
            con = ik_constraint_of(data, roles.get(role))
            if con:
                out[side] = con
                break
    return out


def _finish(data: dict, name: str, res: dict, skip: Sequence[str] = ()) -> dict:
    moved = retarget_fk_to_ik(data, name, skip)
    if moved:
        res["ik_targets_keyed"] = sorted({*res.get("ik_targets_keyed", []), *moved})
        res["keyed"] = [k for k in res.get("keyed", []) if _still_keyed(data, name, k)]
    return res


def _still_keyed(data: dict, name: str, entry: str) -> bool:
    bone, _, tl = entry.rpartition(".")
    return tl in ((doc.animations(data)[name].get("bones") or {}).get(bone) or {})


def idle(
    data: dict, name: str = "idle", duration: float = 2.0, intensity: float = 1.0,
    roles: dict[str, str] | None = None, mode: str = "replace",
) -> dict:
    """Breathing idle: chest/torso scale, head and arms lag, slight hip bob."""
    r = resolve_roles(data, roles)
    _anim(data, name, mode)
    i = intensity
    # Planted feet (IK legs): breathe downwards only, so the legs never overstretch.
    hip_base = -1.5 * i if _ik_legs(data, r) else NAN
    plan = [
        ("torso", "scaley", 0.015 * i, 0, 1, NAN),
        ("chest", "scaley", 0.025 * i, -30, 1, NAN),
        ("chest", "scalex", 0.01 * i, -30, 1, NAN),
        ("head", "rotate", 1.5 * i, -60, 1, NAN),
        ("neck", "rotate", 1.0 * i, -45, 1, NAN),
        ("arm_left", "rotate", 2.0 * i, -90, 1, NAN),
        ("arm_right", "rotate", -2.0 * i, -90, 1, NAN),
        ("hand_left", "rotate", 3.0 * i, -130, 1, NAN),
        ("hand_right", "rotate", -3.0 * i, -130, 1, NAN),
        ("hip", "translatey", 1.5 * i, 90, 1, hip_base),
        ("tail", "rotate", 4.0 * i, -100, 1, NAN),
    ]
    used = _cycle(data, name, plan, duration, duration, r)
    return _finish(data, name, {"animation": name, "duration": duration, "keyed": used, "roles": r})


def walk(
    data: dict, name: str = "walk", duration: float = 1.0, stride: float = 25.0,
    arm_swing: float = 20.0, bob: float = 6.0, lean: float = 0.0,
    roles: dict[str, str] | None = None, mode: str = "replace", run: bool = False,
    step_height: float | None = None, stance: float | None = None, facing: int = 1,
) -> dict:
    """Walk (or run) cycle: legs swing in opposition, knees/feet follow, arms
    counter-swing, hips bob twice per cycle, optional forward lean.

    Legs driven by an IK constraint get planted feet instead of FK swings:
    the IK targets are keyed (constant-speed stance, lifted swing of
    `step_height`, `stance` = fraction of the cycle on the ground, default
    0.55 walk / 0.4 run), the hip is lowered so the knees bend, and the result
    reports `ground_speed` (units/s to move the character at so the feet do
    not skate). The foot reaches out by the `stride` leg angle, at most 30
    deg. facing: 1 = the character looks toward +x, -1 toward -x."""
    r = resolve_roles(data, roles)
    _anim(data, name, mode)
    s, a = stride, arm_swing
    legs = _ik_legs(data, r)
    plan = [
        ("leg_left", "rotate", s, 0, 1, NAN),
        ("leg_right", "rotate", -s, 0, 1, NAN),
        ("shin_left", "rotate", s * 0.6, -70, 1, NAN),
        ("shin_right", "rotate", -s * 0.6, -70, 1, NAN),
        ("foot_left", "rotate", -s * 0.4, -120, 1, NAN),
        ("foot_right", "rotate", s * 0.4, -120, 1, NAN),
        ("arm_left", "rotate", -a, 0, 1, NAN),
        ("arm_right", "rotate", a, 0, 1, NAN),
        ("forearm_left", "rotate", -a * 0.5, -60, 1, NAN),
        ("forearm_right", "rotate", a * 0.5, -60, 1, NAN),
        ("hand_left", "rotate", -a * 0.3, -90, 1, NAN),
        ("hand_right", "rotate", a * 0.3, -90, 1, NAN),
        ("hip", "translatey", bob, 90, 2, NAN),
        ("torso", "rotate", 2.0 if not run else 4.0, 90, 2, lean),
        ("head", "rotate", -1.5, 60, 2, -lean * 0.5),
        ("tail", "rotate", 8.0, -90, 2, NAN),
    ]
    # FK keys on an IK-driven leg would be dead: the feet are keyed below.
    dead = {b for con in legs.values() for b in con["bones"]}
    plan = [p for p in plan if r.get(p[0]) not in dead]
    used = _cycle(data, name, plan, duration, duration, r)
    res: dict = {"animation": name, "duration": duration, "keyed": used, "roles": r}
    if legs:
        res["planted_feet"] = _planted_feet(
            data, name, legs, duration, stride, bob, step_height,
            stance if stance is not None else (0.4 if run else 0.55), 1 if facing >= 0 else -1,
            r.get("hip"))
        res["ik_targets_keyed"] = res["planted_feet"].pop("targets")
    return _finish(data, name, res, skip=[c["name"] for c in legs.values()])


def run(data: dict, name: str = "run", duration: float = 0.6, **kw) -> dict:
    kw.setdefault("stride", 45.0)
    kw.setdefault("arm_swing", 40.0)
    kw.setdefault("bob", 14.0)
    kw.setdefault("lean", -8.0)
    return walk(data, name, duration, run=True, **kw)


def squash_scale(data: dict, bone: str, wide: float, tall: float) -> dict:
    """Scale key fields for a squash & stretch meant in SCREEN axes (`wide` =
    horizontal, `tall` = vertical). Bone scale is in the bone's own axes, so
    for a bone pointing up or down (a hip / spine bone at 90 deg) the two are
    swapped: scale x runs along the bone."""
    from .pose import Pose

    rot = math.radians(Pose(data).bones[bone].world_rotation)
    if abs(math.sin(rot)) > abs(math.cos(rot)):
        return {"x": tall, "y": wide}
    return {"x": wide, "y": tall}


def _screen_scale_keys(data: dict, bone: str, keys: list[dict]) -> list[dict]:
    """Scale keys written with x = horizontal, y = vertical -> the bone's axes."""
    if squash_scale(data, bone, 0, 1)["x"] == 1:
        for k in keys:
            k["x"], k["y"] = k["y"], k["x"]
    return keys


def jump(
    data: dict, name: str = "jump", duration: float = 1.2, height: float = 150.0,
    squash: float = 0.15, roles: dict[str, str] | None = None, mode: str = "replace",
) -> dict:
    """Anticipation squash -> takeoff stretch -> apex -> landing squash ->
    settle. Volume-preserving squash/stretch on the hip (wide = 1/tall, in
    screen axes whatever the hip bone's orientation). IK legs: the feet stay
    planted while the body squats (knees bend), leave the ground at takeoff,
    tuck at the apex and land before the body does."""
    r = resolve_roles(data, roles)
    anim = _anim(data, name, mode)
    hip = r.get("hip") or r.get("torso") or r.get("root")
    if hip is None:
        raise AnimationError("jump needs a hip, torso or root bone")
    T = duration
    t_ant, t_off, t_apex, t_land, t_rec = 0.2 * T, 0.3 * T, 0.55 * T, 0.8 * T, 0.9 * T
    set_keys(anim, "bone", hip, "translatey", [
        {"time": 0, "value": 0, "curve": "easeOut"},
        {"time": t_ant, "value": -height * 0.12, "curve": "easeIn"},
        {"time": t_off, "value": height * 0.2, "curve": "easeOutQuad"},
        {"time": t_apex, "value": height, "curve": "easeInQuad"},
        {"time": t_land, "value": -height * 0.08, "curve": "easeOut"},
        {"time": t_rec, "value": height * 0.02, "curve": "easeInOut"},
        {"time": T, "value": 0},
    ], mode="replace")
    sq, st = 1 - squash, 1 + squash
    legs = _ik_legs(data, r)
    # IK legs fold by themselves when the hip drops: squash the upper body
    # only, or scaling the hip would resize the legs and lift the feet.
    body = r.get("torso") if legs and r.get("torso") else hip
    set_keys(anim, "bone", body, "scale", [
        {"time": 0, **squash_scale(data, body, 1, 1), "curve": "easeOut"},
        {"time": t_ant, **squash_scale(data, body, 1 / sq, sq), "curve": "easeOut"},
        {"time": t_off, **squash_scale(data, body, 1 / st, st), "curve": "easeInOut"},
        {"time": t_apex, **squash_scale(data, body, 1, 1), "curve": "easeIn"},
        {"time": t_land, **squash_scale(data, body, 1 / sq, sq), "curve": "easeOutBack"},
        {"time": T, **squash_scale(data, body, 1, 1)},
    ], mode="replace")
    used = [f"{hip}.translatey", f"{body}.scale"]
    for role, amp in (("arm_left", -60), ("arm_right", 60)):
        b = r.get(role)
        if b:
            set_keys(anim, "bone", b, "rotate", [
                {"time": 0, "value": 0, "curve": "easeIn"},
                {"time": t_ant, "value": -amp * 0.3, "curve": "easeOut"},
                {"time": t_apex, "value": amp, "curve": "easeInOut"},
                {"time": t_land, "value": amp * 0.2, "curve": "easeOut"},
                {"time": T, "value": 0},
            ], mode="replace")
            used.append(f"{b}.rotate")
    res: dict = {"animation": name, "duration": T, "keyed": used, "roles": r}
    for side, con in legs.items():
        reach, rest = _chain_geometry(data, con)
        slack = max(0.0, reach - rest)  # how far the hip can rise before the foot lifts
        tuck = 0.12 * reach * (1.0 if side == "left" else 0.7)
        keys = []
        for t, y, curve in (
            (0, 0.0, None), (t_ant, 0.0, None),
            (t_off, max(0.0, height * 0.2 - slack), "easeOutQuad"),
            (t_apex, height - slack + tuck, "easeInQuad"), (t_land, 0.0, None), (T, 0.0, None),
        ):
            ox, oy = _world_to_parent_offset(data, con["target"], 0.0, y)
            keys.append({"time": t, "x": ox, "y": oy, **({"curve": curve} if curve else {})})
        set_keys(anim, "bone", con["target"], "translate", keys, mode="replace")
        res.setdefault("ik_targets_keyed", []).append(con["target"])
    dead = {b for con in legs.values() for b in con["bones"]}
    for role, amp in (("leg_left", 20), ("leg_right", -15)):
        b = r.get(role)
        if b and b not in dead:
            set_keys(anim, "bone", b, "rotate", [
                {"time": 0, "value": 0},
                {"time": t_off, "value": 0, "curve": "easeOut"},
                {"time": t_apex, "value": amp, "curve": "easeIn"},
                {"time": t_land, "value": 0},
            ], mode="replace")
            used.append(f"{b}.rotate")
    return _finish(data, name, res, skip=[c["name"] for c in legs.values()])


def wave(
    data: dict, name: str = "wave", duration: float = 2.0, side: str = "right",
    raise_angle: float = 150.0, waves: int = 3, roles: dict[str, str] | None = None,
    mode: str = "replace",
) -> dict:
    """Raise one arm and wave the hand/forearm `waves` times."""
    r = resolve_roles(data, roles)
    anim = _anim(data, name, mode)
    arm = r.get(f"arm_{side}")
    if arm is None:
        raise AnimationError(f"no arm_{side} bone found (pass roles={{'arm_{side}': ...}})")
    sign = 1 if side == "right" else -1
    up = sign * raise_angle
    T = duration
    set_keys(anim, "bone", arm, "rotate", [
        {"time": 0, "value": 0, "curve": "easeOutBack"},
        {"time": 0.2 * T, "value": up, "curve": "stepped"},
        {"time": 0.8 * T, "value": up, "curve": "easeInOut"},
        {"time": T, "value": 0},
    ], mode="replace")
    used = [f"{arm}.rotate"]
    lower = r.get(f"forearm_{side}") or r.get(f"hand_{side}")
    if lower:
        set_keys(anim, "bone", lower, "rotate", [
            {"time": 0, "value": 0}, {"time": T, "value": 0},
        ], mode="replace")
        oscillate(data, name, lower, "rotate", amplitude=25, period=(0.6 * T) / waves,
                  duration=0.6 * T, phase=0, start=0.2 * T)
        used.append(f"{lower}.rotate")
    return _finish(data, name, {"animation": name, "duration": T, "keyed": used, "roles": r})


def head_motion(
    data: dict, name: str = "nod", duration: float = 1.0, kind: str = "nod",
    amplitude: float = 12.0, repeats: int = 2, roles: dict[str, str] | None = None,
    mode: str = "replace",
) -> dict:
    """kind: "nod" (rotate), "shake" (quick alternating rotation with
    easing out), "tilt" (single slow tilt and back)."""
    r = resolve_roles(data, roles)
    _anim(data, name, mode)
    head = r.get("head")
    if head is None:
        raise AnimationError("no head bone found")
    if kind == "tilt":
        anim = doc.animations(data)[name]
        set_keys(anim, "bone", head, "rotate", [
            {"time": 0, "value": 0, "curve": "easeInOutSine"},
            {"time": duration / 2, "value": amplitude, "curve": "easeInOutSine"},
            {"time": duration, "value": 0},
        ])
    else:
        oscillate(data, name, head, "rotate", amplitude=amplitude,
                  period=duration / repeats, duration=duration, phase=0)
        if kind == "shake":
            keys = doc.animations(data)[name]["bones"][head]["rotate"]
            for k in keys:
                fade = 1 - k.get("time", 0) / duration
                k["value"] = round(k.get("value", 0) * fade, 4)
                k.pop("curve", None)
                k["curve"] = "easeInOutSine"
            set_keys(doc.animations(data)[name], "bone", head, "rotate", keys, mode="replace")
    return {"animation": name, "duration": duration, "keyed": [f"{head}.rotate"], "roles": r}


def blink(
    data: dict, name: str = "blink", duration: float = 3.0, blink_time: float = 0.15,
    at: float | None = None, bones: Sequence[str] | None = None,
    slot: str | None = None, open_attachment: str | None = None,
    closed_attachment: str | None = None, mode: str = "replace",
) -> dict:
    """Blink by squashing eye bones (scaleY) or by swapping a slot's
    attachment to a closed-eyes image."""
    anim = _anim(data, name, mode)
    t0 = duration * 0.8 if at is None else at
    keyed = []
    if slot:
        doc.find_slot(data, slot)
        if not closed_attachment:
            raise AnimationError("slot blink needs closed_attachment")
        open_attachment = open_attachment or doc.find_slot(data, slot).get("attachment")
        set_keys(anim, "slot", slot, "attachment", [
            {"time": 0, "name": open_attachment},
            {"time": t0, "name": closed_attachment},
            {"time": t0 + blink_time, "name": open_attachment},
        ], mode="replace")
        keyed.append(f"{slot}.attachment")
    else:
        r = resolve_roles(data)
        bones = list(bones or [b for b in (r.get("eye_left"), r.get("eye_right"), r.get("eyes")) if b])
        if not bones:
            raise AnimationError("no eye bones found: pass bones=[...] or slot/closed_attachment")
        for b in bones:
            set_keys(anim, "bone", b, "scaley", [
                {"time": 0, "value": 1},
                {"time": t0, "value": 1, "curve": "easeIn"},
                {"time": t0 + blink_time / 2, "value": 0.1, "curve": "easeOut"},
                {"time": t0 + blink_time, "value": 1},
                {"time": duration, "value": 1},
            ], mode="replace")
            keyed.append(f"{b}.scaley")
    return {"animation": name, "duration": duration, "keyed": keyed}


def hover(
    data: dict, bone: str, name: str = "hover", duration: float = 2.0,
    height: float = 10.0, tilt: float = 3.0, mode: str = "replace",
) -> dict:
    _anim(data, name, mode)
    oscillate(data, name, bone, "translatey", amplitude=height, period=duration, duration=duration)
    if tilt:
        oscillate(data, name, bone, "rotate", amplitude=tilt, period=duration, duration=duration, phase=-60)
    return {"animation": name, "duration": duration, "keyed": [f"{bone}.translatey", f"{bone}.rotate"]}


def bounce(
    data: dict, bone: str, name: str = "bounce", duration: float = 0.8,
    height: float = 80.0, squash: float = 0.25, bounces: int = 1, mode: str = "replace",
) -> dict:
    """Ball-style bounce with volume-preserving squash on contact and stretch
    in the air (squash & stretch + timing/spacing principles)."""
    anim = _anim(data, name, mode)
    doc.find_bone(data, bone)
    ty, sc = [], []
    T = duration / bounces
    for i in range(bounces):
        t = i * T
        ty += [
            {"time": t, "value": 0, "curve": "easeOutQuad"},
            {"time": t + T / 2, "value": height, "curve": "easeInQuad"},
        ]
        s1, s2 = 1 - squash, 1 + squash * 0.5
        sc += [
            {"time": t, "x": 1 / s1, "y": s1, "curve": "easeOut"},
            {"time": t + T * 0.12, "x": 1 / s2, "y": s2, "curve": "easeInOut"},
            {"time": t + T / 2, "x": 1, "y": 1, "curve": "easeIn"},
            {"time": t + T * 0.92, "x": 1 / s2, "y": s2, "curve": "easeIn"},
        ]
    ty.append({"time": duration, "value": 0})
    sc.append({"time": duration, "x": 1 / (1 - squash), "y": 1 - squash})
    set_keys(anim, "bone", bone, "translatey", ty, mode="replace")
    set_keys(anim, "bone", bone, "scale", _screen_scale_keys(data, bone, sc), mode="replace")
    return {"animation": name, "duration": duration, "keyed": [f"{bone}.translatey", f"{bone}.scale"]}


def shake(
    data: dict, bone: str, name: str = "shake", duration: float = 0.5,
    intensity: float = 10.0, frequency: float = 18.0, mode: str = "replace",
) -> dict:
    """Damped shake (hit reaction, impact, camera shake on a root bone)."""
    anim = _anim(data, name, mode)
    doc.find_bone(data, bone)
    w = 2 * math.pi * frequency
    decay = 5.0 / duration
    fx = lambda t: intensity * math.exp(-decay * t) * math.sin(w * t)  # noqa: E731
    dfx = lambda t: intensity * math.exp(-decay * t) * (w * math.cos(w * t) - decay * math.sin(w * t))  # noqa: E731
    fy = lambda t: 0.6 * intensity * math.exp(-decay * t) * math.sin(w * 1.3 * t + 1)  # noqa: E731
    dfy = lambda t: 0.6 * intensity * math.exp(-decay * t) * (w * 1.3 * math.cos(w * 1.3 * t + 1) - decay * math.sin(w * 1.3 * t + 1))  # noqa: E731
    n = max(4, int(duration * frequency * 4))
    times = [duration * i / n for i in range(n + 1)]
    keys = function_keys_xy(fx, dfx, fy, dfy, times)
    keys[-1]["x"] = keys[-1]["y"] = 0
    set_keys(anim, "bone", bone, "translate", keys, mode="replace")
    return {"animation": name, "duration": duration, "keyed": [f"{bone}.translate"]}


def color_effect(
    data: dict, slots: Sequence[str], name: str, effect: str = "flash",
    duration: float = 0.3, color: str = "ffffff", times: int = 1, mode: str = "merge",
) -> dict:
    """Slot color effects:
    - "flash": tint-black flash to `color` (rgba2 dark color) and back, the
      standard hit flash that works on any texture
    - "fadeIn" / "fadeOut": alpha 0 -> 1 / 1 -> 0
    - "pulse": alpha pulse `times` times
    - "tint": rgba tint to `color` and back
    """
    anim = doc.animations(data).setdefault(name, {}) if mode == "merge" else _anim(data, name, mode)
    c6 = color.lstrip("#")[:6].lower()
    for s in slots:
        slot = doc.find_slot(data, s)
        base = (slot.get("color") or "ffffffff").lower()
        if effect == "flash":
            if "dark" not in slot:
                slot["dark"] = "000000"
            keys = []
            for i in range(times):
                t = i * duration / times
                d = duration / times
                keys += [
                    {"time": t, "light": base, "dark": c6, "curve": "easeOut"},
                    {"time": t + d, "light": base, "dark": "000000"},
                ]
            set_keys(anim, "slot", s, "rgba2", keys, mode="replace")
        elif effect in ("fadeIn", "fadeOut"):
            a0, a1 = (0, 1) if effect == "fadeIn" else (1, 0)
            set_keys(anim, "slot", s, "alpha", [
                {"time": 0, "value": a0, "curve": "easeInOut"},
                {"time": duration, "value": a1},
            ], mode="replace")
        elif effect == "pulse":
            keys = []
            for i in range(times):
                t = i * duration / times
                d = duration / times
                keys += [
                    {"time": t, "value": 1, "curve": "easeInOutSine"},
                    {"time": t + d / 2, "value": 0.3, "curve": "easeInOutSine"},
                ]
            keys.append({"time": duration, "value": 1})
            set_keys(anim, "slot", s, "alpha", keys, mode="replace")
        elif effect == "tint":
            set_keys(anim, "slot", s, "rgba", [
                {"time": 0, "color": base, "curve": "easeInOut"},
                {"time": duration / 2, "color": c6 + base[6:8], "curve": "easeInOut"},
                {"time": duration, "color": base},
            ], mode="replace")
        else:
            raise AnimationError("effect must be flash, fadeIn, fadeOut, pulse or tint")
    return {"animation": name, "duration": duration, "slots": list(slots), "effect": effect}


def swap_draw_order(
    data: dict, name: str, time: float, order: list[str], back_at: float | None = None
) -> None:
    anim = doc.animations(data).setdefault(name, {})
    keys = [{"time": time, "order": order}]
    if back_at is not None:
        keys.append({"time": back_at, "order": None})
    set_draw_order_keys(anim, doc.slot_names(data), keys)


# ------------------------------------------------------------ slot symbols
# Reel-game symbol animations. They animate ONE bone that carries the whole
# symbol (by default the only child of root, else root) plus optional slots
# for flashes / glows, and they all start and end on the setup pose so they
# chain cleanly at runtime (land -> idle, idle -> win -> idle, dim / undim).
# Timing follows the classic principles: anticipation before the pop,
# overshoot + damped wobble after it (follow-through), squash & stretch on
# impact. Every value is a parameter; keys stay editable in Spine.


# Slot or attachment names that mark the reel-cell tile itself (background,
# frame, cell, cell mask): the symbol presets must not move them, or the frame
# leaves its cell in the reel grid. The tile word must be the FIRST word of the
# name (fond, case_interieur, frame_gold...), so "texte_case_01" or a shine
# mask ("eclat_masque" clipping) are not taken for the tile.
_TILE_NAME = re.compile(
    r"^(bg|background|backdrop|fond|frame|cadre|border|bord|tile|carreau|case|"
    r"cell|panel)([_\-\s.\d]|$)", re.IGNORECASE)


def tile_slots(data: dict) -> list[str]:
    """Slots that draw the symbol's tile: slot or setup attachment named
    bg / background / fond / frame / cadre / border / tile / case / cell...
    (first word of the name)."""
    return [s["name"] for s in doc.slots(data)
            if _TILE_NAME.search(s["name"]) or _TILE_NAME.search(s.get("attachment") or "")]


def _subtree_slots(data: dict, bone: str) -> list[str]:
    tree = {bone, *doc.descendants(data, bone)}
    return [s["name"] for s in doc.slots(data) if s["bone"] in tree]


def _tile_warnings(data: dict, bone: str) -> list[str]:
    moved = [s for s in tile_slots(data) if s in _subtree_slots(data, bone)]
    if not moved:
        return []
    return [f"bone '{bone}' also moves the tile slots {moved} (background / frame / "
            f"cell mask): the frame will leave its reel cell. Pass params.bone = the "
            f"character bone instead."]


def symbol_bone(data: dict, bone: str | None = None) -> str:
    """`bone`; else the symbol container (the only child of root, followed
    down through slot-less single-child bones, else root). When the container
    also carries the tile (background / frame / cell mask, see tile_slots),
    the tile-free child subtree that holds at least 2/3 of the other slots
    (the character) is chosen; if none dominates, the container is kept and
    the preset result carries a warning."""
    if bone:
        doc.find_bone(data, bone)
        return bone
    root = doc.bones(data)[0]["name"]
    children = doc.children_of(data, root)
    if len(children) != 1:
        return root
    cur = children[0]
    owned = {s["bone"] for s in doc.slots(data)}
    while cur not in owned and len(doc.children_of(data, cur)) == 1:
        cur = doc.children_of(data, cur)[0]
    tiles = set(tile_slots(data))
    if not tiles & set(_subtree_slots(data, cur)):
        return children[0]  # no tile under the container: unchanged behaviour
    # Pick the character: the tile-free child subtree holding most of the
    # non-tile slots (>= 2/3). Several comparable subtrees (two characters,
    # ornaments) stay ambiguous: keep the container, the preset warns.
    sizes = {c: len(sl) for c in doc.children_of(data, cur)
             if (sl := _subtree_slots(data, c)) and not tiles & set(sl)}
    if not sizes:
        return cur
    best = max(sizes, key=sizes.get)
    others = [s for s in _subtree_slots(data, cur) if s not in tiles]
    return best if 3 * sizes[best] >= 2 * len(others) else cur


def _with_warnings(data: dict, res: dict) -> dict:
    w = _tile_warnings(data, res["bone"])
    if w:
        res["warnings"] = w
    return res


def _slot_base_color(data: dict, slot: str) -> str:
    return (doc.find_slot(data, slot).get("color") or "ffffffff").lower()


def _scale_rgb(c8: str, k: float) -> str:
    rgb = [max(0, min(255, round(int(c8[i:i + 2], 16) * k))) for i in (0, 2, 4)]
    return "".join(f"{v:02x}" for v in rgb) + c8[6:8]


def symbol_idle(
    data: dict, bone: str | None = None, name: str = "idle", duration: float = 2.0,
    breathe: float = 0.025, float_height: float = 3.0, sway: float = 1.2,
    mode: str = "replace",
) -> dict:
    """Subtle living loop for a symbol at rest: breathing scale with a slow
    float, and a counter-phased sway. Starts on the setup pose and loops
    seamlessly (every component's period is `duration`)."""
    b = symbol_bone(data, bone)
    _anim(data, name, mode)
    keyed = []
    if breathe:
        oscillate(data, name, b, "scale", amplitude=breathe, period=duration, duration=duration)
        keyed.append(f"{b}.scale")
    if float_height:
        oscillate(data, name, b, "translatey", amplitude=float_height, period=duration,
                  duration=duration)
        keyed.append(f"{b}.translatey")
    if sway:
        oscillate(data, name, b, "rotate", amplitude=sway, period=duration, duration=duration, phase=180)
        keyed.append(f"{b}.rotate")
    return _with_warnings(data, {"animation": name, "duration": duration, "bone": b, "keyed": keyed, "loop": True})


def symbol_land(
    data: dict, bone: str | None = None, name: str = "land", duration: float = 0.45,
    drop: float = 70.0, squash: float = 0.18, rebound: float = 0.1, mode: str = "replace",
) -> dict:
    """Symbol landing at reel stop: falls from `drop` units above (stretched,
    accelerating), squashes on impact, rebounds `rebound` x drop and settles
    on the setup pose."""
    b = symbol_bone(data, bone)
    anim = _anim(data, name, mode)
    d = duration
    hit = 0.38 * d
    ty = [
        {"time": 0, "value": drop, "curve": "easeInQuad"},
        {"time": hit, "value": 0, "curve": "easeOutQuad"},
        {"time": hit + 0.22 * d, "value": drop * rebound, "curve": "easeInQuad"},
        {"time": hit + 0.42 * d, "value": 0, "curve": "easeOutSine"},
        {"time": d, "value": 0},
    ]
    s = squash
    sc = [
        {"time": 0, "x": 1 - s * 0.4, "y": 1 + s * 0.5, "curve": "easeInQuad"},
        {"time": hit, "x": 1 + s, "y": 1 - s, "curve": "easeOutBack"},
        {"time": hit + 0.2 * d, "x": 1 - s * 0.25, "y": 1 + s * 0.3, "curve": "easeInOutSine"},
        {"time": hit + 0.42 * d, "x": 1 + s * 0.12, "y": 1 - s * 0.12, "curve": "easeInOutSine"},
        {"time": d, "x": 1, "y": 1},
    ]
    set_keys(anim, "bone", b, "translatey", ty, mode="replace")
    set_keys(anim, "bone", b, "scale", _screen_scale_keys(data, b, sc), mode="replace")
    return _with_warnings(data, {"animation": name, "duration": d, "bone": b, "impact_time": round(hit, 4),
            "keyed": [f"{b}.translatey", f"{b}.scale"], "loop": False})


def symbol_win(
    data: dict, bone: str | None = None, name: str = "win", duration: float = 1.2,
    pop: float = 0.22, anticipation: float = 0.08, wiggle: float = 7.0, hop: float = 10.0,
    flash_slots: Sequence[str] | None = None, flash_color: str = "ffffff",
    glow_slots: Sequence[str] | None = None, mode: str = "replace",
) -> dict:
    """Winning-symbol celebration: a short squeeze (anticipation), a big pop
    with overshoot, a jelly wobble (alternating x/y stretch + damped rotation)
    and a settle back to the setup pose (loops cleanly for repeated wins).

    flash_slots: slots that get a tint-black flash to `flash_color` on the
    pop (works on any texture). glow_slots: e.g. additive glow images, faded
    0 -> 1 -> 0 around the pop (their setup alpha is left untouched)."""
    b = symbol_bone(data, bone)
    anim = _anim(data, name, mode)
    d, p, a = duration, pop, anticipation
    t_sq, t_pop = 0.12 * d, 0.3 * d
    sc = [
        {"time": 0, "x": 1, "y": 1, "curve": "easeInOutSine"},
        {"time": t_sq, "x": 1 - a * 0.6, "y": 1 - a, "curve": "easeOutCubic"},
        {"time": t_pop, "x": 1 + p, "y": 1 + p, "curve": "easeInOutSine"},
        {"time": 0.42 * d, "x": 1 + p * 0.65, "y": 1 + p * 1.1, "curve": "easeInOutSine"},
        {"time": 0.54 * d, "x": 1 + p * 1.0, "y": 1 + p * 0.7, "curve": "easeInOutSine"},
        {"time": 0.66 * d, "x": 1 + p * 0.85, "y": 1 + p * 0.85, "curve": "easeInOutSine"},
        {"time": 0.86 * d, "x": 1.0 + p * 0.06, "y": 1.0 + p * 0.06, "curve": "easeInOutSine"},
        {"time": d, "x": 1, "y": 1},
    ]
    w = wiggle
    rot = [
        {"time": 0, "value": 0, "curve": "easeInOutSine"},
        {"time": t_pop, "value": w, "curve": "easeInOutSine"},
        {"time": 0.42 * d, "value": -w * 0.75, "curve": "easeInOutSine"},
        {"time": 0.54 * d, "value": w * 0.45, "curve": "easeInOutSine"},
        {"time": 0.66 * d, "value": -w * 0.2, "curve": "easeInOutSine"},
        {"time": 0.78 * d, "value": 0},
        {"time": d, "value": 0},
    ]
    ty = [
        {"time": 0, "value": 0, "curve": "easeInOutSine"},
        {"time": t_sq, "value": -hop * 0.2, "curve": "easeOutCubic"},
        {"time": t_pop, "value": hop, "curve": "easeInOutSine"},
        {"time": 0.66 * d, "value": hop * 0.3, "curve": "easeInOutSine"},
        {"time": d, "value": 0},
    ]
    set_keys(anim, "bone", b, "scale", _screen_scale_keys(data, b, sc), mode="replace")
    set_keys(anim, "bone", b, "rotate", rot, mode="replace")
    keyed = [f"{b}.scale", f"{b}.rotate"]
    if hop:
        set_keys(anim, "bone", b, "translatey", ty, mode="replace")
        keyed.append(f"{b}.translatey")
    c6 = flash_color.lstrip("#")[:6].lower()
    for s in flash_slots or []:
        slot = doc.find_slot(data, s)
        slot.setdefault("dark", "000000")
        base = _slot_base_color(data, s)
        set_keys(anim, "slot", s, "rgba2", [
            {"time": 0, "light": base, "dark": "000000", "curve": "easeInQuad"},
            {"time": t_pop, "light": base, "dark": c6, "curve": "easeOutQuad"},
            {"time": 0.62 * d, "light": base, "dark": "000000"},
        ], mode="replace")
        keyed.append(f"{s}.rgba2")
    for s in glow_slots or []:
        doc.find_slot(data, s)
        set_keys(anim, "slot", s, "alpha", [
            {"time": 0, "value": 0, "curve": "easeInQuad"},
            {"time": t_pop, "value": 1, "curve": "easeOutSine"},
            {"time": 0.9 * d, "value": 0},
        ], mode="replace")
        keyed.append(f"{s}.alpha")
    return _with_warnings(data, {"animation": name, "duration": d, "bone": b, "pop_time": round(t_pop, 4),
            "keyed": keyed, "loop": True})


def symbol_anticipation(
    data: dict, bone: str | None = None, name: str = "anticipation", duration: float = 1.0,
    tremble: float = 2.5, frequency: float = 14.0, swell: float = 0.06, beats: int = 2,
    mode: str = "replace",
) -> dict:
    """Tease / near-win loop (e.g. 2 scatters landed, waiting for the 3rd):
    a fast tremble plus a heartbeat-like swell. The tremble frequency is
    rounded so the loop is seamless."""
    b = symbol_bone(data, bone)
    _anim(data, name, mode)
    cycles = max(1, round(frequency * duration))
    keyed = []
    if tremble:
        oscillate(data, name, b, "rotate", amplitude=tremble, period=duration / cycles, duration=duration)
        keyed.append(f"{b}.rotate")
    if swell:
        oscillate(data, name, b, "scale", amplitude=swell / 2, period=duration / max(1, beats),
                  duration=duration, base=1 + swell / 2, phase=-90)
        keyed.append(f"{b}.scale")
    return _with_warnings(data, {"animation": name, "duration": duration, "bone": b, "tremble_hz": cycles / duration,
            "keyed": keyed, "loop": True})


def symbol_dim(
    data: dict, slots: Sequence[str] | None = None, name: str = "dim", duration: float = 0.25,
    amount: float = 0.45, alpha: float | None = None, mode: str = "replace",
) -> dict:
    """Darken non-winning symbols while the wins play: rgb x `amount` (and
    alpha to `alpha` if given) over `duration`, then hold. Play the setup
    pose (or an empty animation) to undim. Default: every slot."""
    anim = _anim(data, name, mode)
    names = list(slots) if slots else doc.slot_names(data)
    for s in names:
        base = _slot_base_color(data, s)
        end = _scale_rgb(base, amount)
        if alpha is not None:
            end = end[:6] + f"{max(0, min(255, round(alpha * 255))):02x}"
        set_keys(anim, "slot", s, "rgba", [
            {"time": 0, "color": base, "curve": "easeOutQuad"},
            {"time": duration, "color": end},
        ], mode="replace")
    return {"animation": name, "duration": duration, "slots": names, "loop": False}


SLOT_PRESETS = {
    "symbol_idle": symbol_idle,
    "symbol_land": symbol_land,
    "symbol_win": symbol_win,
    "symbol_anticipation": symbol_anticipation,
    "symbol_dim": symbol_dim,
}


PRESETS = {
    "idle": idle,
    "walk": walk,
    "run": run,
    "jump": jump,
    "wave": wave,
    "nod": head_motion,
    "blink": blink,
}
