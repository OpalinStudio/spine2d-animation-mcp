# Production Animation Recipes (`spine2d-mcp`)

Copy and adapt these battle-tested key structures. Always adjust amplitudes to the character's proportions and weight class (see [acting-and-timing.md](acting-and-timing.md)), then run the Pass 4 Critique Loop.

---

## Recipe 1 — Living Idle Loop + Track-1 Blink

**Goal:** A character that breathes, shifts weight subtly, and feels alive without distracting jitter (`2.4 s` loop, 30 fps).

1. **Seed or block base breathing (`2.4 s` loop):**
   - `hip` `translatey`: `0.00 -> 0`, `1.20 -> +4`, `2.40 -> 0` (all `easeInOutSine`).
   - `hip` `translatex`: `0.00 -> -2`, `1.20 -> +2`, `2.40 -> -2` (`easeInOutSine`, subtle weight shift).
   - `torso` `rotate`: `0.00 -> -1.5`, `1.20 -> +2.0`, `2.40 -> -1.5` (`easeInOutSine`).
   - `torso` `scale` (bone pointing up): `0.00 -> (0.99, 1.01)`, `1.20 -> (1.03, 0.97)`, `2.40 -> (0.99, 1.01)` (`easeInOutSine`).
   - `chest` `rotate`: `0.00 -> -2`, `1.20 -> +3`, `2.40 -> -2` (`easeInOutSine`).
   - `head` `rotate`: counter-rotate slightly so gaze stays steady (`0.00 -> +2`, `1.20 -> -2.5`, `2.40 -> +2`, `easeInOutSine`).
   - `arm_l` / `arm_r` `rotate`: swing subtly out of phase (`±4°` to `±7°`), different amplitudes (avoid twinning!).
2. **Stagger the breath cascade (overlap):**
   - `offset_keys(skeleton, "idle", offset=0, bones=["torso", "chest", "head"], stagger=0.10, wrap=True)`
   - `offset_keys(skeleton, "idle", offset=0.16, bones=["arm_l", "forearm_l", "hand_l"], stagger=0.06, wrap=True)`
   - `offset_keys(skeleton, "idle", offset=0.26, bones=["arm_r", "forearm_r", "hand_r"], stagger=0.06, wrap=True)`
3. **Separate `blink` animation (Track 1 overlay):**
   - Never bake blink into `idle`. Create `"blink"` (`0.14 s`) keying **only** the eye slot attachment (`open -> closed -> open`) or eye bone `scaley` (`1 -> 0.08 -> 1`, `easeIn` / `easeOut`).
4. **Verify:**
   - `analyze_animation(skeleton, "idle", loop=True)` — verify `loop_pop == 0`, `loop_gap == 0`, no `timid_motion`.
   - `runtime_render(..., animation="idle", warmup=1, overlays=[{"track": 1, "animation": "blink", "start": 0.9, "mix_out": 0.05}], format="sheet", background=<bg>)`.

---

## Recipe 2 — Weighty IK Walk Cycle (Zero Foot Slide)

**Goal:** Grounded 2-step walk (`0.96 s` = 28.8f; half-cycle `0.48 s`), facing `+x`, with 2-bone IK legs.

1. **Base generation or manual IK setup:**
   - Start with `generate_animation(skeleton, preset="walk", params={"duration": 0.96, "stride": <~0.35*leg_len>, "step_height": <~0.18*leg_len>, "facing": 1})` OR key manually:
   - **Left foot IK target (`ik_foot_l`):**
     - `translatex`: `0.00 -> +S` (`linear`, planted stance!) → `0.48 -> -S` (`easeInOut`, swing forward) → `0.96 -> +S`.
     - `translatey`: `0.00 -> 0` (`stepped` or flat `linear`) → `0.48 -> 0` (`easeOutQuad` lift) → `0.72 -> +H` (`easeInQuad` drop) → `0.96 -> 0`.
   - **Right foot IK target (`ik_foot_r`):**
     - Copy from left foot shifted by half a cycle:
       `copy_keys(skeleton, "walk", bone_map={"ik_foot_l": "ik_foot_r"}, time_offset=0.48, wrap=True)`.
2. **Hip weight (2 cycles per walk loop!):**
   - Contact (`0.00`, `0.48`) → Down (`0.12`, `0.60`, lowest Y, absorbing weight, `easeOut`) → Passing (`0.24`, `0.72`, highest Y, `easeInOut`) → Up (`0.36`, `0.84`, pushing off).
   - Slight forward lean on `torso` (`-6°` to `-10°` for `+x` facing) + gentle hip sway.
3. **Counter-swinging arms + overlap:**
   - Arms swing opposite to their same-side leg (`arm_l` forward when `ik_foot_r` is forward).
   - `offset_keys(skeleton, "walk", offset=0, bones=["arm_l", "forearm_l", "hand_l"], stagger=0.04, wrap=True)`
   - `offset_keys(skeleton, "walk", offset=0, bones=["arm_r", "forearm_r", "hand_r"], stagger=0.04, wrap=True)`
   - `offset_keys(skeleton, "walk", offset=0.04, bones=["chest", "head"], stagger=0.04, wrap=True)`
4. **Footstep events & draw order:**
   - `add_event_keys(skeleton, "walk", keys=[{"time": 0.0, "name": "footstep"}, {"time": 0.48, "name": "footstep"}])`
5. **Verify:**
   - `analyze_animation(skeleton, "walk", loop=True, ground_bones=["ik_foot_l", "ik_foot_r"])` → confirm **zero `foot_slide`**, note reported `ground_speed`, verify IK target reach via `runtime_sample`.
   - `runtime_render(..., format="onion", track_bones=["hip", "ik_foot_l", "hand_r", "head"], warmup=1, background=<bg>)`.

---

## Recipe 3 — Snappy Melee Attack (One-Shot, `0.80 s`)

**Goal:** Readable, punchy slash that mixes smoothly back into `idle`.

| Time | Beat | Poses & Curves |
|---|---|---|
| `0.00 s` | **Ready** | Matches idle ready pose (curve: `easeOut` into wind-up). |
| `0.20 s` | **Anticipation** | Coiled back 20–25%: hip drops slightly, torso twists back, weapon arm pulls high/behind, front foot plants firm. Curve: `easeInCubic` (accelerates violently into strike). |
| `0.30 s` | **Strike Extreme** | Full forward extension (`3 frames` travel!): torso lunges forward, weapon sweeps through wide arc, `scale` stretch `(1.12, 0.89)` on impact frame. Fire `add_event_keys([{"time": 0.30, "name": "hit"}])` + optional VFX smear sequence. Curve: `easeOut` into moving hold. |
| `0.40 s` | **Hit-Stop Moving Hold** | Keep extreme pose with +3° extra drift (not frozen!). Flash target/weapon if appropriate. Curve: `easeOut` into overshoot. |
| `0.55 s` | **Overshoot / Recoil** | Body settles slightly past ready (~10%) with weight recovering onto back leg. Curve: `easeInOut`. |
| `0.80 s` | **Ready** | Back to ready pose (identical to `0.00 s` for clean transition mix to `idle`). |

**Polish:**
- Whip drag on weapon arm: `offset_keys(skeleton, "attack", offset=0, bones=["arm_r", "forearm_r", "hand_r", "weapon"], stagger=0.033, wrap=False)` — then verify the `hit` event still aligns with the weapon tip's strike frame via `runtime_sample`!
- Key `set_draw_order_keys` if the weapon swings from behind to in front of the torso.
- Test transition `idle -> attack -> idle` using `runtime_render(..., overlays=[...], mix=0.15)`.

---

## Recipe 4 — Expressive Jump (`1.05 s` One-Shot)

| Time | Beat | Key Motion & Curves |
|---|---|---|
| `0.00 s` | **Ready** | Standing ready pose (`easeOut`). |
| `0.18 s` | **Crouch Anticipation** | `hip` drops, knees bend (IK feet stay planted at `y=0`), arms swing back, subtle squash `(0.90, 1.11)` on vertical torso (`easeInQuad` into launch). |
| `0.26 s` | **Takeoff** | Legs extend, `hip` shoots upward, arms throw up, stretch `(1.16, 0.86)` (`easeOutQuad` up to apex). |
| `0.50 s` | **Apex Hang** | Highest `hip.y`, legs tuck up smoothly (IK foot targets lifted & tucked), torso upright/neutral (`1.0, 1.0`), slight arm float (`easeInQuad` falling down). |
| `0.72 s` | **Pre-Land Stretch** | Legs reach down toward floor, slight vertical stretch `(1.10, 0.91)` (`linear` / `easeIn` into impact). |
| `0.76 s` | **Landing Impact** | IK feet plant at `y=0`, fire `land` event, `hip` compresses deep, squash `(0.84, 1.19)` within 1–2 frames (`easeOutBack` or `easeOut` into rebound). |
| `0.90 s` | **Rebound** | Slight overshoot above neutral (`+30%` of squash), arms settle (`easeInOutSine`). |
| `1.05 s` | **Ready** | Back to neutral ready pose. |

---

## Recipe 5 — IK-to-FK Arm Handoff (Seated / Prop / Track-1 Wave)

**Problem:** An arm rests on a table/prop via IK (`mix=1`), then needs to let go, wave or reach the face, and return smoothly — even when played as a Track-1 overlay over a breathing loop.

1. **Rig:** Chain `shoulder -> arm -> forearm -> hand` under `torso` (never under furniture). Create IK target parented to the armrest/prop bone.
2. **Release IK smoothly (`set_keyframes kind="ik"`):**
   - `t=0.00`: `{"time": 0.0, "mix": 1.0, "bendPositive": <setup_bool>, "curve": "easeInOut"}`
   - `t=0.15`: `{"time": 0.15, "mix": 0.0, "bendPositive": <setup_bool>}`
   - `t=0.85`: `{"time": 0.85, "mix": 0.0, "bendPositive": <setup_bool>, "curve": "easeInOut"}`
   - `t=1.05`: `{"time": 1.05, "mix": 1.0, "bendPositive": <setup_bool>}`
3. **Animate arm in FK** (`arm`, `forearm`, `hand` `rotate`) between `0.10` and `0.95` — do **not** key the IK target!
4. **Swap hand pose** (`set_keyframes(kind="slot", target="hand_r", timeline="attachment", keys=[...])`) on the fastest frame of the lift/drop so the swap is invisible.
5. **Verify over the base loop:**
   Run `runtime_sample` and `runtime_render` with `animation="idle"` and `overlays=[{"track": 1, "animation": "wave", "start": s, "mix_out": 0.15}]` for `s = 0.0`, `0.7`, `1.4` to confirm zero entry snap and correct elbow bend.

---

## Recipe 6 — Facial Expressions with Spine 4.3 Sliders

1. Create clean, short pose animations (e.g. `expr_happy`, `expr_angry`, `expr_hit`) that key only brow/eye/mouth bones or mesh deform offsets from neutral (`t=0`) to full expression (`t=1.0`).
2. Wire sliders once on the rig:
   `add_slider(skeleton, name="happy", animation="expr_happy", time=0, mix=1, additive=True)`
3. In any character animation (`idle`, `attack`, `victory`), key expression intensity with `set_keyframes(kind="slider", target="happy", timeline="time", keys=[...])` — blends cleanly without cluttering face bone timelines.

---

## Recipe 7 — Juicy Slot / Game UI Symbol Suite

**Golden Rule:** Keep cell background / border / frame slots on `root` (or a static `cell_frame` bone) and animate only the character/gem child bone (`symbol_body`), so animations never clip outside the reel grid. Every clip starts and ends on setup pose so the game can chain `land -> idle -> anticipation -> win`.

1. **Seed base suite:**
   - `generate_animation(skeleton, preset="symbol_idle", params={"duration": 2.4})`
   - `generate_animation(skeleton, preset="symbol_land", params={"duration": 0.45})`
   - `generate_animation(skeleton, preset="symbol_win", params={"duration": 1.2, "flash_slots": [...], "glow_slots": [...]})`
   - `generate_animation(skeleton, preset="symbol_anticipation", params={"duration": 0.8})`
   - `generate_animation(skeleton, preset="symbol_dim", params={"duration": 0.25})`
2. **Polish beyond the preset:**
   - Add secondary stagger to sub-parts (crown, gems, eyes, ribbon) using `offset_keys(..., stagger=0.04)`.
   - Add a 2-frame tint-black white flash (`rgba2`) right on the `symbol_win` pop peak and a pulsing additive glow slot behind the hero silhouette.
   - Add particle/sparkle frame sequence (`kind="sequence"`) timed to the peak.
3. **Verify on real reel background:**
   - Always pass `background=<reel_bg_hex>` (never transparent) so additive glows are actually visible.
   - Test chaining `symbol_land -> symbol_win` with `overlays` on track `0` (`mix=0.08`).

---

## Recipe 8 — Final Verification & Game Delivery Pipeline

```
1. analyze_animation(skeleton)                              # check every animation
2. runtime_validate(skeleton)                               # official spine-webgl load test
3. runtime_render(skeleton, ..., format="sheet", background=<bg>)
4. runtime_render(skeleton, ..., format="onion", track_bones=[...], background=<bg>)
5. export_web_preview(skeleton, output="preview.html", background=<bg>, single_file=True, verify=True)
6. spine_import_data(skeleton, project="character.spine", replace=True)          # if Spine installed
7. export_game_pack(project="character.spine", output_dir="export/", format="binary", premultiplied_alpha=True, validate=True)
```
