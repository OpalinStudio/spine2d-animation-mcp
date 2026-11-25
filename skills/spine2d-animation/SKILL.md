---
name: spine2d-animation
description: Directs high-craft Spine 4.3 skeletal rigging and 2D game animation using the spine2d-mcp server. Enforces art readiness checks, animation-ready IK/physics/mesh rigs, multi-pass pose-to-pose animation (blocking, Bezier spacing, overlapping action, squash and stretch, secondary motion), visual inspection via official spine-webgl contact sheets and onion-skin bone trails, and runtime verification. Use whenever creating, rigging, animating, polishing, reviewing, or exporting Spine 2D characters, creatures, props, or slot symbols.
---

# Spine 2D High-Craft Animation Playbook (`spine2d-mcp`)

A valid Spine JSON is **not** a good animation. This skill turns `spine2d-mcp` into a disciplined senior-animator workflow that produces weighty, readable, game-ready Spine 4.3 animations — never stiff, linear, or half-frozen "AI animations".

## Non-Negotiable Rules

1. **See every change with the official runtime.** Never judge an animation from JSON numbers or from a GIF you cannot watch. After every meaningful pass, call `runtime_render` with `format="sheet"` (to judge silhouettes & poses) and `format="onion"` with `track_bones` (to judge arcs & frame spacing). Do **not** rely on `render_preview` for review (it ignores IK, physics, clipping, and constraints).
2. **Never rig broken art.** Run `check_art` on the parts folder before rigging and `check_art(skeleton=...)` after rigging. Fix `hard_edges` and `fragments` with `clean_art`; regenerate or flag parts with `frayed_edges`, `light_fringe`, `soft_art`, or `joint_gap`.
3. **Never deliver linear or timid motion.** Every moving bone segment needs intentional easing (`curve`) unless true constant velocity is required (planted foot stance, wheel, conveyor). Move the **whole body** (pelvis/torso weight shift, counter-rotation, head lag, arms, loose parts) — avoid `timid_motion` where only one limb twitches on a frozen mannequin.
4. **Respect Spine's coordinate system.** Y-up, bone-local transforms, counter-clockwise degrees. Bone timeline values are **offsets from setup pose**; scale is a **multiplier** (`1.0` = setup). Bone scale axes follow the **bone's orientation** (on a bone pointing up at `rotation: 90`, `scaleX` is vertical).
5. **Measure what stills hide.** Use `analyze_animation` and `runtime_sample` to verify loop seams, pops, foot slide, ground speed, IK target reach (`distance == 0`), and overlay entry jumps.
6. **Report honestly.** Always report measured metrics (`analyze_animation`, `runtime_sample`, `runtime_validate`) and explicitly state what was **not** tested (in-engine feel, full-speed playback, target device sizes). Never claim "no issues" from stills alone.

---

## Reference Map (Progressive Disclosure)

Load only the reference file relevant to the current phase:

- **Timing, weight classes, curves, squash/stretch, physics tuning** → [references/acting-and-timing.md](references/acting-and-timing.md)
- **Fixing stiff/robotic defects & every `analyze_animation` warning** → [references/anti-patterns.md](references/anti-patterns.md)
- **Art slicing, AI part generation prompts, PSD & rig architecture** → [references/art-and-rig-prep.md](references/art-and-rig-prep.md)
- **Concrete key-by-key recipes (idle, walk/run, attack, jump, IK/FK handoff, sliders, slot symbols)** → [references/recipes.md](references/recipes.md)
- **Professional Spine 4.3 benchmarks & Esoteric Software study library (20 official rigs + on-demand fetcher)** → [references/pro-benchmarks.md](references/pro-benchmarks.md) & [`scripts/fetch_pro_example.py`](scripts/fetch_pro_example.py)

Also query `spine_reference(...)` on the server whenever you need exact 4.3 format details (`"timelines"`, `"curves"`, `"constraints"`, `"attachments"`, `"presets"`, `"4.3"`).

---

## Phase 0 — Brief & Art Direction (Before Touching Keys)

Before creating keys, lock down five decisions (ask the user only if genuinely ambiguous and material; otherwise infer sensibly and state your choices):

| Parameter | Why it changes every key |
|---|---|
| **Weight & archetype** | Light/cartoon vs medium/hero vs heavy/boss vs snappy UI/slot symbol → sets timing, anticipation length, squash amount, physics damping. |
| **Loop vs one-shot vs track layer** | Loops require identical start/end pose & slope; one-shots return to a shared ready pose for transitions; track layers (e.g. `blink`, `hit`, `wave`) key **only** acting bones. |
| **Game background color** | Required for `runtime_render(..., background="#rrggbb")` — additive glows vanish on transparent backgrounds and silhouettes read differently on dark vs light backdrops. |
| **Transition mix duration** | Typical game `defaultMix` (`0.1`–`0.25 s`) for testing `A -> B` overlays. |
| **Facing & constraints** | Confirm character facing (`+x` vs `-x`, which flips IK `bend_positive` and walk `facing`), existing IK targets, and physics bones. |

---

## Phase 1 — Inspect Art & Rig

1. **Art audit (new or unverified art):**
   - `check_art(images=<dir>)` → inspect the returned annotated sheet.
   - `clean_art(images=<dir>, out_dir=...)` for `hard_edges` and `fragments`.
   - For `frayed_edges`, `light_fringe`, `soft_art`, or `joint_gap`: follow [references/art-and-rig-prep.md](references/art-and-rig-prep.md).
2. **Skeleton audit:**
   - `inspect_skeleton(skeleton, section="summary")` to map bones, slots/draw order, constraints, skins, events, and existing animations.
   - `runtime_render(skeleton, output=..., format="png", debug=True, background=<bg>)` to visually inspect actual joint pivots, bone directions, meshes, and clipping masks.
   - `check_art(skeleton=skeleton)` to catch `joint_gap` (holes opening when limbs bend) and upscaled attachments.
3. **Upgrade the rig before animating (if allowed and needed):**
   - **2-bone limbs with IK** (`add_ik_constraint(..., create_target=True)`): pass `orient_to_child=True` if the last limb bone has length 0 so Spine solves for the real tip. Verify `bend_positive` matches knee/elbow bend direction (`bend_positive=False` for forward knees when facing `+x`).
   - **Physics on loose parts** (`add_physics_constraint` on hair, ears, cape, tail, coat, belly) — see tuning table in [references/acting-and-timing.md](references/acting-and-timing.md).
   - **Weighted meshes** (`add_mesh_attachment(..., mode="grid", weight_bones=[...])`) where limbs, tails, or cloth must bend smoothly without hard breaks.
   - **4.3 Sliders** (`add_slider`) for reusable facial expressions / pose blends.

---

## Phase 2 — Multi-Pass Animation Workflow

Never try to nail poses, curves, overlap, and polish in a single blind dump of keys. Work in four disciplined passes:

### Pass 1: Block Storytelling Poses (`stepped`)
- Identify the 3–6 **storytelling poses** first (e.g. Ready → Anticipation → Extreme/Contact → Hold/Follow-through → Overshoot → Ready).
- Key them with `set_keyframes(..., keys=[..., {"curve": "stepped"}])` — or seed a locomotion/symbol base with `generate_animation` and immediately inspect it.
- Keep keys minimal and clean (no baked per-frame key soup).
- **Visual gate:**
  `runtime_render(skeleton, output=..., format="sheet", animation=<anim>, times=[<key pose times>], background=<bg>)`
- **Check:** Is every pose readable as a pure silhouette? Does the line of action flow through pelvis → chest → head → acting limb? Are joints intact with no detachment or unintended clipping? Fix poses here before splining.

### Pass 2: Timing, Curves & Arcs (Spline Pass)
- Replace `"stepped"` with deliberate easing presets or cubic-bezier `[x1, y1, x2, y2]` (see [references/acting-and-timing.md](references/acting-and-timing.md)):
  - **Into impact / strike / fall:** `easeIn` / `easeInCubic` / `easeInQuad` (accelerates into force)
  - **Out of impact / takeoff / snap:** `easeOut` / `easeOutCubic` / `easeOutQuint` (fast launch, smooth deceleration)
  - **Cycles, breathing, settles:** `easeInOutSine` / `easeInOut` / `smooth`
  - **Pops, UI, snappy recoil:** `easeOutBack` (overshoot built in)
  - **Constant-speed ground contact (planted IK foot):** `linear`
- **Build real arcs:** Rotations produce arcs naturally; for translations (hips, IK feet, floating props), split `translatex` and `translatey` onto separate timelines with different curves (`translatex` linear + `translatey` `easeOut` then `easeIn` = true parabola).
- **Add volume-preserving squash & stretch** on impacts, launches, and peaks: always keep `scaleX * scaleY ≈ 1.0` (e.g. `1.18` and `0.85`).
- **Visual gate:**
  `runtime_render(skeleton, output=..., format="onion", animation=<anim>, track_bones=[<head, hands, feet, weapon_tip>], warmup=<1 if physics loop else 0>, background=<bg>)`
- **Check:** Are bone paths smooth curves (no sharp kinks)? Do frame dots bunch up at cushions/peaks and stretch wide across fast actions?

### Pass 3: Overlap, Secondary Motion & Exaggeration (Polish Pass)
This is what separates amateur rigging from production game animation:

1. **Break simultaneous stops (Overlapping Action):**
   - Cascade delays down every limb/spine chain with `offset_keys`:
     - Loops (`wrap=True`): `offset_keys(skeleton, anim, offset=0, bones=["torso", "chest", "head"], stagger=0.04, wrap=True)`
     - One-shots (`wrap=False`): `offset_keys(skeleton, anim, offset=0, bones=["arm_r", "forearm_r", "hand_r"], stagger=0.035, wrap=False)`
2. **Break symmetry (Anti-Twinning):**
   - Never let left and right limbs mirror identically on the exact same frames unless it is a deliberate symmetrical jump/clap. Shift one side by `0.03`–`0.08 s` (`offset_keys`) and scale its amplitude slightly (`scale_keys(..., factor=0.85)`).
3. **Push readability (Exaggeration):**
   - Game characters are small on screen. If silhouettes look timid on the sheet, amplify the main acting chain with `scale_keys(skeleton, anim, factor=1.25, bones=[...], timelines=["rotate"])`, and soften secondary chains (`factor=0.7`–`0.85`) so the eye knows where to look.
4. **Eliminate dead holds:**
   - During any hold (`0.07`–`0.15 s` hit-stop or pause), keep 2–5% drift, breathing, or physics settle — never a completely frozen silhouette.
5. **Layer polish details:**
   - `set_draw_order_keys` when limbs/weapons cross in front or behind the torso (use `folder_slots` in 4.3 for independent draw-order folders).
   - `add_event_keys` on exact footfalls, impact frames, VFX spawns, and audio cues.
   - Slot swaps (`kind="slot", timeline="attachment"`) for hand poses or mouth/eye shapes — always hide swaps inside a fast motion frame or smoke/smear sequence.
   - Layer independent actions (`blink`, `hit_flash`, `aim`) as separate animations played on track `1+` instead of baking them into every clip.

### Pass 4: Critique Loop (Analyze → Look → Fix → Repeat)

Run this exact verification loop after Pass 3 and repeat until clean:

1. **Quantitative review:**
   `analyze_animation(skeleton, animation=<anim>, ground_bones=[<foot IK targets if walk/run>])`
   - Fix every `error` and `warning` (`loop_pop`, `loop_gap`, `linear_motion`, `dead_keys`, `pop`, `foot_slide`).
   - Review every `info` (`loop_hitch`, `twinning`, `no_overlap`, `squash_volume`, `dead_hold`, `timid_motion`) — fix unless intentionally stylized, and if kept, justify why.
   - Use [references/anti-patterns.md](references/anti-patterns.md) for the exact repair per code.
2. **Visual review (full sheet + onion):**
   - `runtime_render(..., format="sheet", background=<game_bg>, warmup=<1 if loop+physics else 0>)`
   - `runtime_render(..., format="onion", track_bones=[<key extremities>], background=<game_bg>, warmup=<1 if loop+physics else 0>)`
   - Inspect every cell of the sheet for: silhouette clarity, joint gaps, limb stretch/locking, draw order errors, glow visibility on `<game_bg>`.
3. **IK & Overlay checks (when applicable):**
   - **IK reach:** `runtime_sample` on the end bone and its IK target — confirm distance is `~0` (no hyper-extended locked knee/elbow).
   - **Transitions (`A -> B`):** `runtime_render(animation=A, overlays=[{"track": 0, "animation": B, "start": <t>, "loop": True, "mix": 0.2}], duration=<d>, format="sheet", background=<game_bg>)` — ensure no weird intermediate twist or pop.
   - **One-shot layers on Track 1+:** Never review a track layer alone! Test it **over its base loop** at 2–3 different `start` times using `overlays=[{"track": 1, "animation": <layer>, "start": t, "mix_out": 0.2}]` and measure the entry jump with `runtime_sample`. If an arm leaves an IK target, key the **IK constraint mix `1 -> 0 -> 1`** rather than yanking the IK target across the body.

---

## Phase 3 — Delivery & Export Checklist

Before handing back to the user, verify and produce the requested deliverables:

- [ ] `runtime_validate(skeleton, atlas=...)` passes cleanly with zero missing regions or runtime errors.
- [ ] All animations tested on the game's actual background color (mandatory if any slot uses `additive` blend).
- [ ] If replacing an existing game animation: duration and event names/timings preserved unless explicitly changed.
- [ ] Deliverables generated as requested:
  - **Review on desktop/phone:** `export_web_preview(skeleton, output=..., background=<bg>, single_file=True, verify=True)`
  - **Showcase media:** `runtime_render` (`gif` / `webp` / `webm` / `mp4` / `mov`) or `editor_render` (when Spine 4.3 editor is installed and reference export quality is requested)
  - **Editable Spine project:** `spine_import_data(skeleton, project=..., replace=True)`
  - **Production game bundle:** `export_game_pack(project, output_dir, format="binary", premultiplied_alpha=True, validate=True)`
- [ ] Final summary includes:
  1. Animations created/updated (durations, loop status, ground speed if walk/run, events fired),
  2. Measured metrics (`analyze_animation` summary, `amplitude`, `runtime_validate`),
  3. What was visually checked (sheet, onion, transitions),
  4. What was **not** checked (in-engine feel, full-speed playback, other screen sizes) and what — if anything — is faster to fine-tune by hand in the Spine 4.3 editor (weight painting, custom mesh outlines).
