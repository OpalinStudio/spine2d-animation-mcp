# Art Preparation, Part Slicing & Rig Architecture

Most "low quality" Spine animations fail **before the first keyframe** because of bad cut-outs, missing joint underpaint, or rigid single-bone limbs. Follow this guide before rigging.

---

## 1. Designing & Slicing Parts for Animation

### Core Rules
- **Neutral setup pose:** Limbs straight, separated from the torso and from each other, facing flat (no heavy foreshortening). A bent arm drawn into the illustration only ever works in that one pose.
- **One image per moving segment:**
  - Limbs split at real joints: `arm_left`, `forearm_left`, `hand_left`, `leg_left`, `shin_left`, `foot_left` (and `*_right`).
  - Head parts isolated: `head`, `eyes_open`, `eyes_half`, `eyes_closed`, `pupils`, `brows`, mouth shapes (`mouth_rest`, `mouth_smile`, `mouth_open`, `mouth_o`), ears, individual hair locks.
  - Loose/secondary parts isolated: cape panels, scarf, tail, tie, straps, earrings, coat tails.
  - Props isolated: weapon, shield, mug, cigar — drawn **complete** even where fingers cover them.
- **Hidden rounded ends (underpaint):** Every limb segment extends past its joint pivot by **~50% of its thickness** with a rounded cap centered on the pivot, so rotating 40–90° never opens a wedge gap.
- **Closed dark/consistent outlines** help hide overlapping seams cleanly.
- **Swappable hand poses:** Draw 4–6 hands per side (`relaxed`, `open`, `fist`, `hold`, `point`) aligned to the exact same wrist pivot and swap them via slot attachment keys during motion.
- **Frame-by-frame VFX:** Draw 6–16 frames (`smoke_00.png` … `smoke_11.png`) on a region attachment with `sequence_count`, keyed via `set_keyframes(kind="sequence")`. A quick puff or smear also masks attachment swaps cleanly.
- **Resolution & margins:** Paint/generate at **2×** final in-game display size, uniform line weight and lighting direction across all parts, with transparent padding around every part (never tightly clipped where it continues under a neighbor).

---

## 2. Generating Clean Parts with an Image Model

When using an image-generation model alongside `spine2d-mcp`:

1. **Step 1 — Character reference sheet (neutral pose):**
   > *"Full-body 2D game character design sheet of [character], standing in a clean neutral A-pose facing right (+X), arms slightly away from the body, straight unbent limbs, consistent bold outlines, flat game shading, plain white/transparent background, no props overlapping the torso."*
2. **Step 2 — One isolated part per request (always attach the reference sheet):**
   > *"Isolate ONLY the [left forearm] of this exact character from the reference sheet. Draw it straight, vertical, complete with BOTH rounded ends extending slightly past the elbow and wrist joints (underpaint for 2D skeletal rigging). Exact same line weight, palette, and lighting direction as the sheet. Clean antialiased edges on a pure transparent background. Nothing else in the image."*
3. **Step 3 — Automated Art QA Gate (`check_art` → `clean_art` → regenerate):**
   Run `check_art(images=<parts_dir>)` after every batch and inspect the annotated contact sheet:

| `check_art` Warning | Meaning | Action |
|---|---|---|
| `hard_edges` | Aliased 1-bit mask (stair-stepping when rotated). | Repair with `clean_art(images, out_dir)` (antialiases inward without resizing). |
| `fragments` | Stray detached pixels floating around the part. | Repair with `clean_art(images, out_dir, fragments=True)`. |
| `frayed_edges` | Spiky / torn cut-out contour. | **Regenerate/redraw** quoting the warning's `fix` text (only use `clean_art(..., smooth=...)` if the part has no intentional fur/whiskers, and visually inspect). |
| `light_fringe` | White/bright halo from background removal. | **Regenerate/redraw** on clean alpha; `clean_art` cannot fix color contamination baked into semi-transparent edge pixels. |
| `see_through` | Accidental semi-transparent holes inside solid fill. | **Regenerate/redraw** opaque interior. |
| `soft_art` | Part noticeably blurrier than sibling parts. | **Regenerate** at matching sharpness/resolution. |
| `upscaled` / `stretched` | Attachment rendered larger than source pixel dimensions (skeleton check). | Re-export part at higher resolution or reduce attachment scale. |
| `joint_gap` | Bending the joint by `±25°` opens a visible hole (skeleton check). | **Regenerate/redraw** the named part with a longer rounded hidden end, OR bridge the joint with a weighted mesh (`add_mesh_attachment(..., weight_bones=[...])`). |

---

## 3. PSD → Rig Conventions (`import_psd_to_spine`)

When starting from a layered PSD:
- **Standard humanoid names** automatically wire up the bone hierarchy and spine chain:
  `hip`/`pelvis`, `body`/`torso`, `chest`, `neck`, `head`, `arm_left`/`right`, `forearm_left`/`right`, `hand_left`/`right`, `leg_left`/`right`, `shin_left`/`right`, `foot_left`/`right`.
- **Two-segment limbs required for real IK knees/elbows:** include `forearm_*` and `shin_*`.
- **Grouping:** Layers inside a `head` group parent to `head`; any group tagged `[bone]` creates a bone; layers named `<part>[pivot]` set exact custom pivots; `[ignore]` skips guides/backgrounds.
- **Recommended call:**
  ```
  import_psd_to_spine(
    psd_path="hero.psd",
    orient_bones=True,
    export_images=True,
    ik_legs=True,
    ik_arms=False
  )
  ```
- **Immediate post-import check:**
  1. `runtime_render(skeleton, output=..., format="png", debug=True)` — verify every pivot sits directly on its joint center; adjust with `update_bone(..., keep_world_position=True)`.
  2. `check_art(skeleton=skeleton)` — fix any `joint_gap` before animating.

---

## 4. Animation-Ready Rig Checklist

Before writing animation keyframes, verify the rig supports expressive motion:

1. **Root / Hip Hierarchy:**
   - `root` stays at `(0, 0)` on the ground plane (never move `root` for body bob — move `hip`/`pelvis` so planted IK foot targets stay anchored to `root`).
   - Spine chain (`hip → torso → chest → neck → head`) points upward with non-zero bone lengths so rotations feel intuitive.
2. **2-Bone Leg IK (Mandatory for Walk / Run / Jump):**
   - `add_ik_constraint(skeleton, bones=["leg_l", "shin_l"], create_target=True, target_parent="root", bend_positive=False, orient_to_child=True)` (for `+x` facing; flip `bend_positive=True` for `-x` facing).
   - Keep `foot_l` child of `shin_l` with `inherit="noRotationOrReflection"` (or animate foot rotation independently) so planted feet stay flat on the floor.
   - Add a small `softness` (`5–10%` of leg length) to prevent snappy knee-lock pops.
3. **Arm Setup (FK vs IK):**
   - **Default to FK** for swings, combat, and gestures (natural arcs, easy `offset_keys` stagger).
   - **Use IK** when hands must stay pinned to a weapon grip, prop, armrest, or wall (`target_parent=<prop_or_root>`). Remember: use `orient_to_child=True` if the forearm has length 0, and fade IK `mix` to `0` whenever the arm releases into FK!
4. **Weighted Meshes for Bending Parts:**
   - For tails, capes, tentacles, or single-piece elastic limbs:
     `add_mesh_attachment(skeleton, slot, name, mode="grid", width=W, height=H, cols=max(4, round(W/30)), rows=max(2, round(H/30)), weight_bones=[bone1, bone2, bone3])`
   - Always inspect mesh deformation visually with `runtime_render(..., debug={"bones": True, "meshes": True})`.
5. **Physics Constraints on Loose Parts:**
   - Add chains via `add_physics_constraint(skeleton, bones=["hair_1", "hair_2", "hair_3"], rotate=1.0, inertia=0.75, strength=140, damping=0.88, chain_falloff=0.15)`.
   - Verify constraint update order (`update_constraint(..., order_index=...)`): **IK / Transform / Path / Sliders MUST update BEFORE Physics** so physics reacts to the final posed skeleton!
6. **4.3 Facial Sliders:**
   - Create short pose animations (`expr_smile`, `expr_angry`, `expr_surprised`), then wire them with `add_slider(skeleton, name="smile", animation="expr_smile", bone="face_ctrl", property="y", scale=0.02, additive=True)` — or key slider `time` directly in animations.
7. **Slot / Reel-Cell Symbols:**
   - Keep background/frame/cell-border slots on `root` (or a static `frame` bone) and put the animated character/gem under its own child bone (`hero_root` / `symbol_body`), so `symbol_win` / `symbol_land` never shake the tile frame out of its grid cell.
