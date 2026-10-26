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
from typing import Callable, Sequence

from . import document as doc
from .animation import AnimationError, set_draw_order_keys, set_keys

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


def idle(
    data: dict, name: str = "idle", duration: float = 2.0, intensity: float = 1.0,
    roles: dict[str, str] | None = None, mode: str = "replace",
) -> dict:
    """Breathing idle: chest/torso scale, head and arms lag, slight hip bob."""
    r = resolve_roles(data, roles)
    _anim(data, name, mode)
    i = intensity
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
        ("hip", "translatey", 1.5 * i, 90, 1, NAN),
        ("tail", "rotate", 4.0 * i, -100, 1, NAN),
    ]
    used = _cycle(data, name, plan, duration, duration, r)
    return {"animation": name, "duration": duration, "keyed": used, "roles": r}


def walk(
    data: dict, name: str = "walk", duration: float = 1.0, stride: float = 25.0,
    arm_swing: float = 20.0, bob: float = 6.0, lean: float = 0.0,
    roles: dict[str, str] | None = None, mode: str = "replace", run: bool = False,
) -> dict:
    """Walk (or run) cycle: legs swing in opposition, knees/feet follow, arms
    counter-swing, hips bob twice per cycle, optional forward lean."""
    r = resolve_roles(data, roles)
    _anim(data, name, mode)
    s, a = stride, arm_swing
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
    used = _cycle(data, name, plan, duration, duration, r)
    return {"animation": name, "duration": duration, "keyed": used, "roles": r}


def run(data: dict, name: str = "run", duration: float = 0.6, **kw) -> dict:
    kw.setdefault("stride", 45.0)
    kw.setdefault("arm_swing", 40.0)
    kw.setdefault("bob", 14.0)
    kw.setdefault("lean", -8.0)
    return walk(data, name, duration, run=True, **kw)


def jump(
    data: dict, name: str = "jump", duration: float = 1.2, height: float = 150.0,
    squash: float = 0.15, roles: dict[str, str] | None = None, mode: str = "replace",
) -> dict:
    """Anticipation squash -> takeoff stretch -> apex -> landing squash ->
    settle. Volume-preserving squash/stretch on the hip (scale x = 1/y)."""
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
    set_keys(anim, "bone", hip, "scale", [
        {"time": 0, "x": 1, "y": 1, "curve": "easeOut"},
        {"time": t_ant, "x": 1 / sq, "y": sq, "curve": "easeOut"},
        {"time": t_off, "x": 1 / st, "y": st, "curve": "easeInOut"},
        {"time": t_apex, "x": 1, "y": 1, "curve": "easeIn"},
        {"time": t_land, "x": 1 / sq, "y": sq, "curve": "easeOutBack"},
        {"time": T, "x": 1, "y": 1},
    ], mode="replace")
    used = [f"{hip}.translatey", f"{hip}.scale"]
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
    for role, amp in (("leg_left", 20), ("leg_right", -15)):
        b = r.get(role)
        if b:
            set_keys(anim, "bone", b, "rotate", [
                {"time": 0, "value": 0},
                {"time": t_off, "value": 0, "curve": "easeOut"},
                {"time": t_apex, "value": amp, "curve": "easeIn"},
                {"time": t_land, "value": 0},
            ], mode="replace")
            used.append(f"{b}.rotate")
    return {"animation": name, "duration": T, "keyed": used, "roles": r}


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
    return {"animation": name, "duration": T, "keyed": used, "roles": r}


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
    set_keys(anim, "bone", bone, "scale", sc, mode="replace")
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


PRESETS = {
    "idle": idle,
    "walk": walk,
    "run": run,
    "jump": jump,
    "wave": wave,
    "nod": head_motion,
    "blink": blink,
}
