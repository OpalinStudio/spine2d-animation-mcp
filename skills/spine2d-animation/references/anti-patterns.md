# Animation Anti-Patterns & Diagnostic Repair Guide

Use this guide whenever `analyze_animation`, `runtime_sample`, or visual inspection of a `sheet` / `onion` reveals a defect. Every code below matches the exact output of `spine2d-mcp`.

---

## 1. `analyze_animation` Code → Exact Fix Matrix

| Code | Severity | What It Means Visually | Exact Repair |
|---|---|---|---|
| `loop_pop` | `warning` | Visible teleport/snap when the loop wraps from `duration` back to `0`. | Key the exact same value at `time=duration` as `time=0` on every looping timeline (`set_keyframes`, `mode="merge"`). Don't forget IK targets! |
| `loop_gap` | `warning` | After IK/constraints run in the official runtime, a bone ends away from its start pose. | Inspect the named bone + its parent/IK target at `t=0` and `t=duration` via `runtime_sample`; match end keys to start keys (and check IK `bendPositive`). |
| `loop_hitch` | `info` | A subtle rhythmic "tick" at the loop seam because entry and exit slopes don't match. | Match tangents across the seam (e.g. `easeInOutSine` peaking cleanly away from `t=0`), or shift the phase with `offset_keys(..., wrap=True)` which splits Bezier handles cleanly via de Casteljau. |
| `linear_motion` | `warning` | Robotic, constant-velocity puppet motion; evenly spaced dots on `onion`. | Add `"curve"` presets (`easeInOut`, `easeOut`, `easeIn`, `easeOutBack`) with `set_keyframes(..., mode="merge")`. Keep `linear` only on planted foot contact segments. |
| `stepped_motion` | `info` | Animation is still in Pose-to-Pose blocking (`"stepped"`). | Expected after Pass 1; replace `"stepped"` with eased curves in Pass 2. |
| `dead_keys` | `warning` | Rotation keys written on bones owned by an IK constraint at `mix=1` — they are silently ignored! | Animate the **IK target**'s `translate` instead, OR key the IK constraint's `mix` to `0` (`set_keyframes(kind="ik", target=<ik_name>, keys=[{"time": ..., "mix": 0}])`) for an FK section, and remove unused rotation keys (`clear_timeline`). |
| `pop` | `warning` | A bone jumps violently in a single frame (IK knee flip, missing key, or stray stepped curve). | Render `runtime_render(..., format="sheet", times=[t-0.06, t-0.03, t, t+0.03, t+0.06])` around the reported `t`. Check if an IK target crossed the limb line (causes knee/elbow flip) or exceeded limb reach; adjust target path or `softness`. |
| `foot_slide` | `warning` | Foot skates forward/backward while planted on the ground during a walk/run. | Ensure the IK foot target moves at **constant velocity (`linear`)** along X from contact to toe-off while Y stays flat at ground height. Report `ground_speed` from `analyze_animation` so the game engine moves the character at the matching speed. |
| `twinning` | `info` | Left and right limbs do the exact same motion on the exact same frames — looks stiff/mirrored. | Offset one side by `0.03–0.10 s` with `offset_keys(bones=[other_side], offset=0.06, wrap=...)` and slightly vary amplitude with `scale_keys(bones=[other_side], factor=0.85)`. |
| `no_overlap` | `info` | Every bone in a chain (`arm → forearm → hand` or `torso → chest → head`) hits extremes simultaneously like a wooden plank. | Run `offset_keys(bones=[parent, child, tip], offset=0, stagger=0.04, wrap=<bool>)` to create organic drag and follow-through. |
| `squash_volume` | `info` | Bone inflates or shrinks unnaturally during squash & stretch (`scaleX * scaleY ≠ 1`). | Enforce `scaleY = 1 / scaleX` (e.g. `x: 1.15, y: 0.87`). Check bone rotation to make sure X and Y match the visual stretch axis. |
| `dead_hold` | `info` | Everything freezes completely for ≥ 0.25 s — reads as a stuck/broken frame. | Convert to a **moving hold**: drift 2–5% toward the follow-through direction (`easeOut`), keep breathing on chest/head, or attach physics to hair/cape. |
| `timid_motion` | `info` | Most drawn bones barely move (`<50%` active or `<2%` of character size) — looks like a static image with one twitching part. | Engage the whole body: add hip weight shift, chest breath/counter-rotation, head counter-tilt, subtle arm sway, and physics on loose parts. Push acting chains with `scale_keys(factor=1.3–2.0)` and check silhouettes on a sheet. |
| `spin` | `info` | Bone rotates > 180° between two keys (often caused by wrapping `-170°` to `+170°`). | Check the signed angle delta; if a short turn was intended, use the equivalent angle (`-170°` → `-190°`) instead of crossing ±180°. |
| `key_soup` | `info` | Over-baked timeline (>20 keys/sec) that is heavy and painful to edit in Spine. | Rebuild the motion with 3–8 strategic keys and proper Bezier curves (or run `spine_clean_up` on the `.spine` project). |

---

## 2. Visual Defects You Catch ONLY on `sheet` and `onion`

Even when `analyze_animation` reports `0 warnings`, look closely at the rendered pictures for these classic failures:

### Broken Arcs (Catch on `onion`)
- **Symptom:** The dotted trail of a hand, foot, or weapon tip forms sharp V-corners or straight triangles.
- **Cause:** Keying `translate` linearly between 3 points, or rotating a limb without counter-moving the parent.
- **Fix:** Add an in-between breakdown key pushing the midpoint outward along the arc, or split `translatex` (`linear`) and `translatey` (`easeOut` / `easeIn`).

### Even Spacing / Floaty Weight (Catch on `onion`)
- **Symptom:** Frame dots along a trajectory are equally spaced everywhere, making an attack feel underwater or a jump feel weightless.
- **Cause:** Weak easing (`easeInOutSine` used on a punch) or flat timing.
- **Fix:** Bunch dots tightly during anticipation and apex (`easeOut` into peak), then leave wide gaps across the strike/fall (`easeInCubic` / `easeInExpo`).

### Muddy Silhouette (Catch on `sheet`)
- **Symptom:** Weapon, arm, or head overlaps the torso so the action is unreadable at game scale.
- **Cause:** Small poses, wrong draw order, or limb moving across the body instead of opening into negative space.
- **Fix:** Push the acting limb outside the torso silhouette, tilt the torso into the line of action, and use `set_draw_order_keys` so the active limb reads cleanly in front.

### Hyper-Extended / Snapping IK Limbs (Catch on `sheet` + `runtime_sample`)
- **Symptom:** Knee or elbow snaps rigidly straight and vibrates when the target approaches max reach.
- **Cause:** IK target travels farther than `len(upper) + len(lower)`, or `softness` is `0`.
- **Fix:**
  1. Add slight `softness` (`update_constraint(..., fields={"softness": 12})` — ~5–10% of limb length) to cushion near full extension.
  2. Measure `runtime_sample` on the wrist/ankle bone vs its IK target bone: distance must stay `0`. Pull the target slightly inward or drop the hip bone lower.

### Missing Additive Glows (Catch on `sheet`)
- **Symptom:** Fire, magic aura, or slot-win glow looks invisible.
- **Cause:** Rendered on a transparent background (`background=None`). Additive blending adds RGB to background pixels — over empty alpha, there is nothing to add to.
- **Fix:** Always pass the real game backdrop (`background="#1b1d22"` or equivalent) to `runtime_render`.

### Track-1 Overlay Snap / Wrong Elbow Bend (Catch on `overlays` review)
- **Symptom:** A `wave` or `aim` animation looks fine alone, but snaps violently or bends the elbow backward when triggered over `idle` or `walk`.
- **Cause:**
  1. Keying an IK target in a track-1 layer without mix-in makes the limb teleport from wherever the base loop placed the target.
  2. An IK timeline key omitting `bendPositive` defaults to `true`, silently flipping an arm/leg whose setup pose has `bendPositive: false`.
- **Fix:**
  1. Test every track layer over its base loop at multiple `start` times (`runtime_render(..., overlays=[{"track": 1, "animation": layer, "start": t, "mix_out": 0.2}])` and `runtime_sample`).
  2. To release an arm from an IK target cleanly, key the IK `mix` from `1 -> 0 -> 1` and animate the arm bones in FK, preserving explicit `bendPositive` on any IK key.

### Unwarmed Physics Jump at `t=0` (Catch on `sheet` with `warmup`)
- **Symptom:** Hair or cape starts stiff/vertical on frame 1 and suddenly whips backward on frame 2.
- **Cause:** Physics simulation starts from rest at `t=0`.
- **Fix:** Always pass `warmup=1` (or `2`) to `runtime_render` and `runtime_sample` when reviewing looping animations with physics constraints.
