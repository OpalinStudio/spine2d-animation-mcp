"""Keyframe curves: easing presets -> Spine bezier arrays, and evaluation.

Spine stores a key's interpolation to the NEXT key in its `curve` field:
- absent: linear
- "stepped": hold the value until the next key
- [cx1, cy1, cx2, cy2, ...]: one cubic bezier per animated value (4 numbers
  each, in the timeline's value order). Control points are ABSOLUTE: cx in
  seconds, cy in the value's own units (degrees, pixels, 0..1 color...).

Tools accept friendlier inputs and convert here:
- a preset name ("easeInOut", "easeOutBack", ...), CSS/easings.net style
- a normalized [x1, y1, x2, y2] cubic-bezier (like CSS `cubic-bezier()`),
  applied to every value of the key
- {"raw": [...]} to pass an absolute Spine curve through unchanged
- {"per_value": [(x1, y1, x2, y2), ...]}: one normalized bezier per value
"""

from __future__ import annotations

from typing import Any, Sequence

# Normalized cubic-bezier control points (x1, y1, x2, y2).
EASING_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "ease": (0.25, 0.1, 0.25, 1.0),
    "easeIn": (0.42, 0.0, 1.0, 1.0),
    "easeOut": (0.0, 0.0, 0.58, 1.0),
    "easeInOut": (0.42, 0.0, 0.58, 1.0),
    "easeInSine": (0.12, 0.0, 0.39, 0.0),
    "easeOutSine": (0.61, 1.0, 0.88, 1.0),
    "easeInOutSine": (0.37, 0.0, 0.63, 1.0),
    "easeInQuad": (0.11, 0.0, 0.5, 0.0),
    "easeOutQuad": (0.5, 1.0, 0.89, 1.0),
    "easeInOutQuad": (0.45, 0.0, 0.55, 1.0),
    "easeInCubic": (0.32, 0.0, 0.67, 0.0),
    "easeOutCubic": (0.33, 1.0, 0.68, 1.0),
    "easeInOutCubic": (0.65, 0.0, 0.35, 1.0),
    "easeInQuart": (0.5, 0.0, 0.75, 0.0),
    "easeOutQuart": (0.25, 1.0, 0.5, 1.0),
    "easeInOutQuart": (0.76, 0.0, 0.24, 1.0),
    "easeInQuint": (0.64, 0.0, 0.78, 0.0),
    "easeOutQuint": (0.22, 1.0, 0.36, 1.0),
    "easeInOutQuint": (0.83, 0.0, 0.17, 1.0),
    "easeInExpo": (0.7, 0.0, 0.84, 0.0),
    "easeOutExpo": (0.16, 1.0, 0.3, 1.0),
    "easeInOutExpo": (0.87, 0.0, 0.13, 1.0),
    "easeInCirc": (0.55, 0.0, 1.0, 0.45),
    "easeOutCirc": (0.0, 0.55, 0.45, 1.0),
    "easeInOutCirc": (0.85, 0.0, 0.15, 1.0),
    "easeInBack": (0.36, 0.0, 0.66, -0.56),
    "easeOutBack": (0.34, 1.56, 0.64, 1.0),
    "easeInOutBack": (0.68, -0.6, 0.32, 1.6),
    # Spine's default "auto"-ish smooth key, close to the editor's ease.
    "smooth": (0.333, 0.0, 0.667, 1.0),
}


def preset_names() -> list[str]:
    return sorted(EASING_PRESETS)


def _norm_spec(spec: Any) -> tuple[float, float, float, float] | str | None:
    """Return a normalized bezier, "stepped", or None (linear)."""
    if spec is None:
        return None
    if isinstance(spec, str):
        if spec == "stepped":
            return "stepped"
        if spec == "linear":
            return None
        key = spec.strip()
        if key not in EASING_PRESETS:
            # Tolerate case/underscore variants: ease_in_out, EASEINOUT.
            lowered = {k.lower(): k for k in EASING_PRESETS}
            key = lowered.get(key.replace("_", "").replace("-", "").lower(), "")
            if not key:
                raise ValueError(
                    f"unknown curve preset {spec!r}; use 'linear', 'stepped', a "
                    f"preset ({', '.join(preset_names())}) or [x1, y1, x2, y2]"
                )
        return EASING_PRESETS[key]
    if isinstance(spec, (list, tuple)) and len(spec) == 4:
        x1, y1, x2, y2 = (float(v) for v in spec)
        if not (0.0 <= x1 <= 1.0 and 0.0 <= x2 <= 1.0):
            raise ValueError("normalized bezier x1/x2 must be within [0, 1]")
        return (x1, y1, x2, y2)
    raise ValueError(f"invalid curve {spec!r}")


def to_spine_curve(
    spec: Any,
    t1: float,
    t2: float,
    values1: Sequence[float],
    values2: Sequence[float],
) -> list[float] | str | None:
    """Convert a curve spec for the segment (t1, values1) -> (t2, values2)
    into the Spine `curve` field value (or None for linear)."""
    if isinstance(spec, dict) and "raw" in spec:
        raw = spec["raw"]
        return raw if isinstance(raw, str) else [float(v) for v in raw]
    if isinstance(spec, dict) and "per_value" in spec:
        # One normalized bezier per value (used to rescale existing curves).
        dt = t2 - t1
        out: list[float] = []
        for (x1, y1, x2, y2), a, b in zip(spec["per_value"], values1, values2):
            dv = b - a
            out.extend([_r(t1 + x1 * dt), _r(a + y1 * dv), _r(t1 + x2 * dt), _r(a + y2 * dv)])
        return out
    norm = _norm_spec(spec)
    if norm is None or norm == "stepped":
        return norm
    x1, y1, x2, y2 = norm
    if (x1, y1, x2, y2) == EASING_PRESETS["linear"]:
        return None
    dt = t2 - t1
    out: list[float] = []
    for v1, v2 in zip(values1, values2):
        dv = v2 - v1
        out.extend(
            [
                _r(t1 + x1 * dt),
                _r(v1 + y1 * dv),
                _r(t1 + x2 * dt),
                _r(v1 + y2 * dv),
            ]
        )
    return out


def _r(v: float) -> float:
    v = round(v, 6)
    return 0.0 if v == 0 else v


def bezier_value(
    time: float,
    t1: float,
    v1: float,
    cx1: float,
    cy1: float,
    cx2: float,
    cy2: float,
    t2: float,
    v2: float,
) -> float:
    """Evaluate a Spine absolute bezier segment at `time` (solves x(s)=time)."""
    if t2 <= t1:
        return v2
    lo, hi = 0.0, 1.0
    s = (time - t1) / (t2 - t1)
    for _ in range(40):
        x = _cubic(s, t1, cx1, cx2, t2)
        if abs(x - time) < 1e-7:
            break
        if x < time:
            lo = s
        else:
            hi = s
        s = (lo + hi) / 2.0
    return _cubic(s, v1, cy1, cy2, v2)


def _cubic(s: float, p0: float, p1: float, p2: float, p3: float) -> float:
    u = 1.0 - s
    return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3
