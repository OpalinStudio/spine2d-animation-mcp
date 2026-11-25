# Acting, Timing, Curves & Physics Reference

Use these concrete numbers when blocking and splining animations in `spine2d-mcp`. All frame counts assume **30 fps** (`1 frame = 0.0333 s`; `skeleton.fps`).

---

## 1. Character Weight Classes

Pick a weight class before setting key times. The exact same poses feel completely different depending on timing and spacing.

| Weight Class | Examples | Anticipation | Main Action (Snap) | Impact Hold | Overshoot / Settle | Squash & Stretch | Physics Damping / Strength |
|---|---|---|---|---|---|---|---|
| **Light / Cartoon** | Mascot, rogue, sprite, slime | `0.10–0.15 s` (3–4f) | `0.07–0.10 s` (2–3f) | `0.07 s` (2f) | `0.20–0.30 s` (`easeOutBack`, 15–25% overshoot) | Generous: `15–30%` (`1.25 / 0.80`) | Light & bouncy: strength `80–140`, damping `0.88–0.94` |
| **Medium / Hero** | Adventurer, soldier, archer | `0.13–0.20 s` (4–6f) | `0.08–0.13 s` (2–4f) | `0.07–0.10 s` (2–3f) | `0.22–0.33 s` (10–15% overshoot) | Controlled: `8–15%` (`1.12 / 0.89`) | Crisp: strength `130–200`, damping `0.84–0.90` |
| **Heavy / Boss** | Knight, golem, mech, ogre | `0.25–0.45 s` (8–14f) | `0.10–0.17 s` (3–5f) | `0.13–0.20 s` (4–6f) | `0.35–0.55 s` (heavy slow settle, minimal bounce) | Subtle: `5–10%` on impact only (`0.92 / 1.09`) | Heavy: mass `1.5–2.5`, strength `60–110`, damping `0.78–0.85` |
| **UI / Slot Symbol** | Gems, icons, badges, chests | `0.08–0.12 s` (2–4f) | `0.10–0.18 s` (3–5f) | `0.07–0.10 s` (2–3f) | `0.25–0.40 s` (jelly decay) | Punchy: `15–25%` (`1.20 / 0.83`) | Snappy spring: strength `180–260`, damping `0.85–0.90` |

---

## 2. Standard Action Timing Table

| Action | Duration | Beat Breakdown |
|---|---|---|
| **Blink (track 1)** | `0.12–0.15 s` | `0.00` open → `0.04` closed (`easeIn`) → `0.08` closed → `0.14` open (`easeOut`). Trigger irregularly every `2–5 s` in game. |
| **Breathing Idle (loop)** | `2.0–3.6 s` | `0.00` exhale low → `0.45–0.50 × dur` inhale high (`easeInOutSine`) → `1.00 × dur` exhale low (`easeInOutSine`). Stagger chest/head/arms by `0.06–0.15 s`. |
| **Alert / Combat Idle** | `1.0–1.6 s` | Faster rhythmic bounce (`~0.7–1.0 Hz`), knees slightly bent on IK, weight rocking subtly front/back, weapon floating with lag. |
| **Walk Cycle (2 steps)** | `0.80–1.10 s` | Per step (half cycle): Contact (`0%`), Down (`12–15%`, lowest hip), Passing (`25%`, highest hip), Up/Push-off (`38–40%`). |
| **Run Cycle (2 steps)** | `0.50–0.70 s` | Forward torso lean `10–18°`, two airborne flight phases per cycle, high knee drive, sharp arm pump. |
| **Jump (full one-shot)** | `0.95–1.25 s` | Crouch anticipation `0.16–0.22 s` → Takeoff stretch `0.08–0.10 s` → Rise + Apex hang + Fall `0.40–0.55 s` → Landing squash `0.08–0.12 s` → Rebound + Settle `0.22–0.30 s`. |
| **Fast Melee Attack** | `0.60–0.85 s` | Wind-up `0.16–0.22 s` → Slash `0.07–0.10 s` (event `hit` at end) → Hit-stop moving hold `0.08–0.12 s` → Overshoot `0.12 s` → Return to ready `0.20–0.28 s`. |
| **Heavy Slam Attack** | `1.10–1.50 s` | Big wind-up `0.35–0.45 s` (easeOut into peak) → Accelerate slam `0.12–0.15 s` (`easeInCubic`) → Impact hold + root shake `0.15–0.20 s` → Heavy pull-up `0.45–0.65 s`. |
| **Hit Reaction** | `0.40–0.55 s` | Snap recoil `0.05–0.08 s` (`easeOutExpo`) + tint-black flash `0.10–0.13 s` → Recoil hold `0.08–0.10 s` → Recover `0.25–0.35 s` (`easeInOut`). |
| **Victory / Pop** | `0.30–0.45 s` pop + `1.0–1.5 s` loop | Scale `0 → 1.15` (`0.15 s`, `easeOutBack`) → `0.97` (`0.08 s`) → `1.0` (`0.10 s`), paired with slight counter-rotation. |

---

## 3. Curve Presets Cheat Sheet (`set_keyframes`)

Every key's `"curve"` shapes interpolation from **that key to the next key**. All exact presets supported by `spine2d-mcp`:

| Category | Exact Preset Names | When to Use |
|---|---|---|
| **Hold / Linear** | `"stepped"`, `"linear"` | `"stepped"` for blocking & instant swaps; `"linear"` ONLY for planted foot stance, rolling wheels, conveyors, or constant-speed horizontal travel. |
| **Soft / Natural Cycles** | `"smooth"`, `"ease"`, `"easeInOut"`, `"easeInOutSine"`, `"easeInOutQuad"` | Breathing idles, gentle settles, floating, head turns, organic loops. |
| **Slow-In (Accelerate)** | `"easeIn"`, `"easeInSine"`, `"easeInQuad"`, `"easeInCubic"`, `"easeInQuart"`, `"easeInQuint"`, `"easeInExpo"`, `"easeInCirc"` | Falling under gravity, accelerating into a punch/slash, pulling out of anticipation into strike. Higher power (`Cubic`→`Expo`) = snappier whip. |
| **Slow-Out (Decelerate)** | `"easeOut"`, `"easeOutSine"`, `"easeOutQuad"`, `"easeOutCubic"`, `"easeOutQuart"`, `"easeOutQuint"`, `"easeOutExpo"`, `"easeOutCirc"` | Rising to jump apex, arriving into anticipation pose, cushioning out of an impact or hit recoil. |
| **Snappy S-Curves** | `"easeInOutCubic"`, `"easeInOutQuart"`, `"easeInOutQuint"`, `"easeInOutExpo"`, `"easeInOutCirc"` | Fast whip transitions that cushion at both ends (quick turns, snappy UI slides). |
| **Built-in Overshoot** | `"easeOutBack"`, `"easeInBack"`, `"easeInOutBack"` | `"easeOutBack"` for pops/landings/snappy settles; `"easeInBack"` for automatic micro-anticipation before a launch. |
| **Custom Cubic Bezier** | `[x1, y1, x2, y2]` (`x1, x2 ∈ [0, 1]`) | Fine control: e.g. `[0.15, 0.95, 0.35, 1.0]` for ultra-snappy arrival; `[0.65, 0.0, 0.85, 0.15]` for heavy hang-time before drop. |

### Parabolic Arc Trick (Translations)
Spine's `translate` uses one curve spec for both X and Y unless you split timelines. To get a real parabolic arc (jump, tossed prop, lifted foot):
- Key `timeline="translatex"` with `"linear"` (constant forward velocity).
- Key `timeline="translatey"` with `"easeOutQuad"` going up to apex and `"easeInQuad"` falling down from apex.
Verify with `runtime_render(..., format="onion", track_bones=[...])`: the dotted trail should form a clean parabola, never a triangle.

---

## 4. Volume-Preserving Squash & Stretch

`analyze_animation` flags `squash_volume` whenever `scaleX * scaleY` drifts more than `0.15` from `1.0` during opposite-sign squash/stretch.

Use exact reciprocal pairs (`y = 1 / x`):

| Feel | Stretch (`scaleX`, `scaleY`) | Squash (`scaleX`, `scaleY`) |
|---|---|---|
| Subtle (realistic/heavy) | `(1.06, 0.94)` | `(0.94, 1.06)` |
| Crisp (hero game) | `(1.12, 0.89)` | `(0.88, 1.14)` |
| Juicy (cartoon / UI) | `(1.20, 0.83)` | `(0.82, 1.22)` |
| Extreme (smear / impact) | `(1.30, 0.77)` | `(0.76, 1.32)` |

**CRITICAL — Bone Axis Check:**
- `scaleX` stretches **along the bone's length** (its local +X axis).
- If a torso or root-child bone points straight up (`rotation ≈ 90°`), `scaleX` is vertical height and `scaleY` is horizontal width.
- If a bone has `rotation = 0°` (pointing right, like a default root/symbol container), `scaleY` is vertical height and `scaleX` is horizontal width!
- Always check bone orientation with `inspect_skeleton` or `runtime_render(..., debug=True)` before keying scale.
- For IK limbs and physics, Spine 4.3 supports `scale_y="volume"` directly on `add_ik_constraint(..., stretch=True, scale_y="volume")` and `add_physics_constraint(..., scale_x=..., scale_y="volume")`.

---

## 5. Spine 4.3 Physics Tuning Matrix (`add_physics_constraint`)

Physics only reacts when the parent bone **moves**. Always render looping animations with `warmup=1` (or `2` for long chains) so physics is already settled at `t=0`.

| Material / Part | Properties (`x, y, rotate, scale_x`) | `inertia` | `strength` | `damping` | `mass` | `gravity` / `wind` | `chain_falloff` |
|---|---|---|---|---|---|---|---|
| **Short hair / bangs / ears** | `rotate=1.0` | `0.6–0.8` | `130–200` | `0.85–0.90` | `0.8–1.0` | `gravity=0–5` | `0.15` |
| **Long ponytail / scarf** | `rotate=1.0` | `0.8–1.0` | `70–110` | `0.90–0.94` | `1.0` | `gravity=8–18`, optional wind | `0.18` |
| **Cape / long coat** | `rotate=1.0` | `0.85–1.0` | `55–95` | `0.90–0.95` | `1.2` | `gravity=10–22`, wind in idle/run | `0.20` |
| **Fluffy tail / antenna** | `rotate=1.0` | `0.75–0.95` | `80–130` | `0.88–0.93` | `0.9` | `gravity=0–8` | `0.15` |
| **Belly / cheek / jelly jiggle** | `x=0.3, y=1.0, rotate=0, scale_x=0.45, scale_y="volume"` | `0.5–0.65` | `200–300` | `0.78–0.85` | `1.0` | `gravity=0` | `0.10` |
| **Heavy tassel / lantern / weapon charm** | `rotate=1.0` | `0.9–1.0` | `90–140` | `0.92–0.96` | `1.8–2.5` | `gravity=15–30` | `0.10` |

**Tip:** Pass `global_properties=["wind", "gravity"]` when you want to animate gusts of wind across all cloth/hair chains at once using `set_keyframes(kind="physics", target="", timeline="wind", ...)`.

---

## 6. Overlap Stagger Cheat Sheet (`offset_keys`)

| Chain | Recommended `stagger` (seconds) | Frames @ 30fps | Notes |
|---|---|---|---|
| **Spine:** `hip → torso → chest → head` | `0.033–0.066` | 1–2 frames | Keeps upper body fluid without looking rubbery. |
| **Arm whip:** `arm → forearm → hand` | `0.033–0.066` | 1–2 frames | On swings, throws, waves; use `wrap=False` for one-shots. |
| **Long tail / cape (FK):** `seg1 → seg2 → seg3 → seg4` | `0.050–0.100` | 1.5–3 frames | Or use `generate_animation(preset="follow_through")` / physics. |
| **Idle breathing phase shift:** `torso`, `head`, `arm_l`, `arm_r` | Offset `0.08–0.20` between groups | 2–6 frames | Prevents the whole character inflating/deflating in lockstep. |
