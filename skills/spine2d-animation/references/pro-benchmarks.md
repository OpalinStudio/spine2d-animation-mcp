# Professional Spine 4.3 Animation Benchmarks & Reference Library

Instead of inventing synthetic reference animations, study **real professional Spine 4.3 projects** authored by Esoteric Software's animators and game industry specialists. All quantitative metrics below were measured directly from the official Spine 4.3 exports in [`EsotericSoftware/spine-runtimes` (branch `4.3`)](https://github.com/EsotericSoftware/spine-runtimes/tree/4.3/examples).

> **License note:** Esoteric Software's official example assets are distributed under the Spine Runtimes / non-commercial example license (`license.txt` in each example). Never commit them to a third-party repository or ship them in commercial games. Download them on demand to your local cache with `scripts/fetch_pro_example.py` for study and benchmarking only.

---

## 1. Esoteric Software's 8-Part Animation Principles Series (Official Spine 4.3)

Esoteric publishes 8 dedicated masterclass skeletons teaching core animation craft directly in Spine 4.3. Study these whenever you want to see textbook timing, arcs, squash & stretch, anticipation, and overlap:

| Example | Key Animations | What It Teaches | Measured Highlights (4.3) |
|---|---|---|---|
| `1-weight-and-mass` | `animation` (balls), `ready-to-animate` (drop) | Conveying heavy vs light weight strictly through spacing & bounce decay | 9 bones, 273 keys (`3.23 s`) |
| `2-the-12-principles` | `basketball`, `billiard-ball`, `bowling-ball`, `tennis-ball` | Material & mass contrast across 4 balls on the exact same course | `79–99%` Bezier curves (`bowling-ball`: 99% Bezier, `25.87 s`) |
| `3-timing-and-spacing` | `heavy` (`5.33 s`), `light` (`1.67 s`) | Same action transformed purely by frame count & ease distribution | `heavy`: 100% Bezier (`46 keys`); `light`: 89% Bezier (`23 keys`) |
| `4-wave-principle` | `wave-by-hand` (`1.33 s`), `wave-offset` (`1.33 s`), `ball-catch` (`10.0 s`) | Overlapping wave motion down a 6-bone chain; proof that offsetting keys beats hand-keying every joint | `wave-offset` uses **31% fewer keys** than `wave-by-hand` (`24` vs `35`, both 100% Bezier) — directly mirrors `offset_keys(..., stagger=...)` |
| `5-squash-and-stretch` | `ball`, `speedy` (`6.5 s`) | Volume-preserving squash & stretch on a simple ball and a full 16-bone expressive character | `speedy`: 14 bones keyed, `94%` Bezier |
| `6-arcs` | `arcs` (`5.67 s`) | Clean curved motion paths with transform constraints | 14 bones, 4 transform constraints, `97%` Bezier |
| `7-anticipation` (`sack-pro`) | `walk` (`0.67 s`), `hello` (`2.87 s`), `fall-in` (`1.67 s`), `cape-follow-example` (`3.0 s`) | Classic flour-sack anticipation, acting & cloth follow-through with Spine physics | 31 bones, **20 physics + 4 transform constraints**; `walk` is `98%` Bezier, `hello` `95%` Bezier |
| `8-follow-through` | `follow-through` (`3.63 s`, ball & pendulum) | Settling, drag, and damped overshoot after a stop | Pendulum: `99%` Bezier (`165 keys`); Ball: `94%` Bezier |

---

## 2. Esoteric Software's Production Character & Feature Rigs (Spine 4.3)

| Example | Rig Profile | Constraints | Standout Animations & Measured Benchmarks |
|---|---|---|---|
| `spineboy` (`spineboy-pro`) | 67 bones, 52 slots, `footstep` event | `7 IK`, `7 Transform` | Canonical 2D action hero: `idle` (`1.67 s`, 20 bones, 82 keys, **100% Bezier**), `run` (`0.67 s`, 30 bones, 191 keys, **93% Bezier**, 2 `footstep` events), `jump` (`1.33 s`, 30 bones, **99% Bezier**), dedicated `0.27 s` transition clips (`run-to-idle`, `idle-turn`), surgical Track-1 layers (`shoot`: only 9 bones; `aim`: only 5 bones). |
| `celestial-circus` (`celestial-circus-pro`) | 60 bones, 70 slots | `30 Physics`, `3 Transform` | Official Spine physics showcase: lush hair, ribbons, and dress react automatically to `swing` (`2.2 s`) and `wind-idle` (`9.63 s`). Blink lives on separate track clips (`eyeblink` `0.33 s` & `eyeblink-long` `4.7 s`, 6 bones, **100% Bezier**). |
| `diamond` (`diamond-pro`) | 8 bones, 30 slots | `1 Slider` | Official **Spine 4.3 Slider** faux-3D showcase: a single slider maps `diamond-rotation-control.rotate` (`scale = 0.005555556 = 2.0 / 360`, `loop = true`, `local = true`) directly onto the `2.0 s` multi-slot `rotation` animation. |
| `owl` (`owl-pro`) | 20 bones, 27 slots | `10 Physics`, `1 Transform` | 2.5D head turn via additive/layered directional poses (`up`, `down`, `left`, `right` 0s poses) + physics on tail/ear feathers (`inertia=0.77, x=0.20, scaleX=0.05`) + independent `blink`. |
| `mix-and-match` (`mix-and-match-pro`) | 143 bones, 80 slots, **34 skins** | `2 IK`, `4 Path`, `17 Transform` | Production modular dress-up character with linked meshes & skin-required bones: `idle` (`1.17 s`), `walk` (`0.67 s`), `dance` (`0.50 s`), `dress-up` (`2.77 s`), `blink` (`1.03 s`). |
| `raptor` (`raptor-pro`) | 76 bones, 36 slots, `footstep` event | `9 IK` | Heavy creature locomotion & full-body follow-through: `walk` (`1.27 s`, 56 bones, **88% Bezier**, 2 `footstep` events), `roar` (`2.13 s`, 72 bones, **88% Bezier**), `jump` (`1.53 s`, 55 bones, **91% Bezier**), surgical Track-1 prop layers (`gun-grab` & `gun-holster`: only 3 bones, **100% Bezier**). |
| `hero` (`hero-pro`) | 44 bones, 31 slots, 3 skins, `footstep` event | `3 IK`, `1 Path` | Compact action-platformer knight with path-constrained cape, `attack` (`0.40 s`), `run` (`0.53 s`, 2 `footstep` events), `crouch`, `fall`, `idle-from fall`, `crouch-from fall`, `head-turn`. |
| `cloud-pot` | 29 bones, 29 slots | `26 Physics` | Soft-body physics benchmark: `pot-moving-followed-by-rain` keys **only 1 bone**, `playing-in-the-rain` keys **only 5 bones**, while 26 physics constraints (`strength=172.8, damping=0.857, mass=3, x=1, y=1`) generate fluid secondary motion. |
| `snowglobe` (`snowglobe-pro`) | 86 bones, 111 slots | `47 Physics`, `4 Transform` | Clipping dome + dense physics snow/foliage (`idle` `2.1 s`, `shake` `2.1 s`, `eyeblink` `0.63 s` 100% Bezier). |
| `chibi-stickers` | 44 bones, 62 slots, **11 skins** | `2 IK`, `1 Transform` | Fast, expressive UI/emote library (`emotes/angry`, `excited`, `crying`, `confused`, `flushed`…): `0.4–2.0 s` clips averaging just `20–80 keys` each. |
| `stretchyman` (`stretchyman-pro`) | 55 bones, 9 slots | `4 IK`, `4 Path`, `2 Transform` | Elastic rubber-hose limbs driven by IK + Path constraints (`sneak` `1.8 s`, 28 bones, **83% Bezier**). |
| `coin` (`coin-pro`) | 7 bones, 6 slots | None | Minimalist faux-3D spinning pickup / slot-symbol coin (`2.67 s`, only 3 bones keyed, 69 keys, 60% Bezier) using mesh deformation & draw-order flips. |

---

## 3. Six Patterns Distilled from Pro Spine 4.3 Files

Apply these concrete lessons from Esoteric's rigs to your own work:

1. **High Bezier discipline on hero motion:** In `spineboy-pro`, `raptor-pro`, `7-anticipation`, and `8-follow-through`, **88%–100%** of moving bone segments use Bezier curves. Linear segments are reserved strictly for constant-speed contacts or mechanical turns.
2. **Whole-body involvement (no timid frozen mannequins):** `spineboy-pro`'s `idle` moves 20 bones (`1.67 s`, only 82 keys — roughly 4 keys per bone!) and `run` moves 30 bones. Richness comes from distributing a **few well-curved keys across the whole skeleton**, not baking 50 keys onto one bone.
3. **Surgical Track-1 overlays:** `spineboy`'s `shoot` (9 bones) and `aim` (5 bones), `raptor`'s `gun-grab` (3 bones), and `celestial-circus`/`snowglobe`'s `eyeblink` (4–6 bones) are all isolated clips that never touch unrelated bones so they layer cleanly over locomotion or idle.
4. **Dedicated short transition clips (`0.25–0.55 s`):** Instead of relying purely on linear crossfades (`mix`), pro rigs include short bridge clips like `spineboy`'s `run-to-idle` (`0.267 s`), `idle-turn` (`0.267 s`), or `hero`'s `idle-from fall` (`0.567 s`).
5. **Let physics & sliders do repetitive work:** `cloud-pot` drives 29 bones by keying 1–5 driver bones + 26 physics constraints; `diamond-pro` drives 30 slots of faux-3D rotation from 1 rotated bone via a single Spine 4.3 Slider (`scale = duration / 360`).
6. **Offset beats hand-keying for waves:** Esoteric's `4-wave-principle` proves directly that `wave-offset` (`offset_keys(..., stagger=...)`) produces cleaner motion with ~30% fewer keys than keying each segment manually.

---

## 4. Study Any Pro Example Live with `spine2d-mcp`

Use the bundled helper script to fetch any official Esoteric Software Spine 4.3 example on demand into your local cache (`~/Library/Caches/spine2d-mcp/pro-examples/` on macOS, or `$SPINE_MCP_CACHE/pro-examples/`):

```bash
# List all 20 curated Spine 4.3 pro examples
python3 skills/spine2d-animation/scripts/fetch_pro_example.py --list

# Download an example (e.g. spineboy, celestial-circus, diamond, 7-anticipation)
python3 skills/spine2d-animation/scripts/fetch_pro_example.py spineboy
```

Then inspect it directly with `spine2d-mcp` to learn from real pro data before animating a similar brief:

1. `inspect_skeleton(skeleton=<cached_json>, section="summary")` — study bone hierarchy, constraint order, and animation list.
2. `analyze_animation(skeleton=<cached_json>, animation="run", ground_bones=[...])` — inspect pro timing, amplitude, and event beats.
3. `runtime_render(skeleton=<cached_json>, output=..., format="png", debug=True)` — see exact pro pivot placement, mesh topology, and IK/path rigs.
4. `runtime_render(skeleton=<cached_json>, output=..., animation="jump", format="onion", track_bones=[...], background="#1b1d22")` — study real pro arcs and dot spacing.
5. `export_web_preview(skeleton=<cached_json>, output=..., single_file=True)` — inspect live playback at `0.25x`–`1x` speed.

---

## 5. Curated External Pro Resources (Web)

- **Esoteric Software — Official Example Project Breakdowns:** https://esotericsoftware.com/spine-examples (detailed write-ups explaining *why* each rig & animation is built the way it is: Spineboy, Celestial Circus, Diamond, Owl, Mix and Match, Cloud Pot, Snowglobe, Raptor, Stretchyman, Coin).
- **Esoteric Software — Live Interactive Web Demos:** https://esotericsoftware.com/spine-demos (inspect Spineboy, Mix and Match, Owl, Physics, and Sliders live in browser).
- **Esoteric Software — Official Spine 4.3 Examples Repository:** https://github.com/EsotericSoftware/spine-runtimes/tree/4.3/examples (source `.spine` files, exported 4.3 JSONs, and the 8 Animation Principles projects).
- **Esoteric Software — Spine Tips & Rigging Videos (Erika / Nate):**
  - Spine User Guide Video Series: https://www.youtube.com/playlist?list=PLwGl7Ikd_6GRFo7d0uRu_fN2RIlvkxW7b
  - Esoteric Software YouTube Channel (Twitch rigging & animation breakdowns, Spine Tips): https://www.youtube.com/user/EsotericSoftware/videos
  - Spine 4.3 Release Notes (Sliders, Transform Mapping, Volumetric ScaleY): https://esotericsoftware.com/blog/Spine-4-3-release
- **Official Commercial Game Showcase (`#madewithspine`):** https://esotericsoftware.com/spine-showcase
- **Arman Harutyunyan (Armanimation) — Pro Spine 2D Studio Workflows & Reel Audits:** https://armanimation.com (art slicing standards, rigging optimization, and animation critique breakdowns).
