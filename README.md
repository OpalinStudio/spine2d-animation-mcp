# spine2d-mcp

An MCP server that lets an AI assistant rig and animate [Spine](http://esotericsoftware.com/) **4.3** characters (Essential / Professional), and drive the Spine editor's command line on **macOS, Windows and Linux**.

It works on Spine skeleton JSON files: every tool loads the file, applies one change, validates the result against the Spine 4.3 reader rules and saves it (an invalid edit is rejected and the file is left untouched). Files exported by the Spine editor round-trip unchanged, so you can go back and forth between the editor and the assistant.

> 🇫🇷 Guide en français : [docs/README.fr.md](docs/README.fr.md)

## What it covers

| Area | Tools |
|---|---|
| **PSD → rig** | `import_psd_to_spine`: layered PSD → bones, slots, region attachments, atlas, per-layer images, oriented bones, optional leg/arm IK and starter animations. Humanoid layer names build the character rig (with `forearm_*` / `shin_*` for real elbows and knees); every other layer is kept with its own bone (parented by group), `[bone]` groups, `[pivot]` markers, `[ignore]`, so props and slot symbols import too |
| **Skeleton** | `create_skeleton`, `inspect_skeleton`, `validate_skeleton` (`target_version` lists what an older export drops), `get_element` |
| **Bones** | `add_bone` (local or world coords), `update_bone` (rename with every reference, reparent keeping the world pose, inherit modes, 4.3 icon size/rotation, visibility, skin-required), `remove_bone` (cascades, remaps mesh weights) |
| **Slots / draw order** | `add_slot`, `update_slot`, `remove_slot`, `set_draw_order` (animation draw-order keys are re-encoded automatically) |
| **Attachments** | region (with image sequences), mesh (grid / polygon outline / explicit), `bind_mesh_weights` (auto weights; existing deform keys converted to the weighted layout), linked mesh (4.3: source in another slot), bounding box, clipping (4.3: inverse + convex), point, path (bezier lengths computed), raw JSON, update, remove |
| **Skins** | `add_skin` (copy), `update_skin` (color, skin bones and constraints, rename), `remove_skin` |
| **Constraints (4.3)** | IK (1-2 bones, target creation, `orient_to_child` points a zero-length bone at its wrist so Spine solves for the right tip, compress/stretch, `scaleY` none/uniform/volume), transform (4.3 property mapping from→to with offset/scale/max, clamp, local source/target, additive), path, physics (single or chain, 4.3 `scaleY`, global properties), **sliders**, update/rename/reorder (array order = update order), remove |
| **Events** | `set_event` (int/float/string/audio/volume/balance), `remove_event`, `add_event_keys` |
| **Animation** | `manage_animation` (create/delete/rename/duplicate, 4.3 color), `set_keyframes` on **every** 4.3 timeline (bone, slot, IK, transform, path, physics incl. skeleton-wide wind/gravity, slider, deform, sequence; single-value timelines only take `value`: `y` on translatey is stored as `value` with a warning, other stray numbers are refused, and `validate_skeleton` warns about fields the reader ignores), easing presets and bezier curves, `set_draw_order_keys` (full or partial orders, **4.3 draw order folders**), `retime_animation`, `clear_timeline` |
| **Key editing** | `offset_keys` (shift keys in time; on a loop the curve is cut exactly at the loop point; `stagger` delays each bone of a chain = overlapping action), `scale_keys` (exaggerate / soften values, curves keep their shape), `copy_keys` (bone → bone or animation → animation, mirrored and half a cycle later for the other side) |
| **Procedural** | `generate_animation`: idle, walk, run, jump, wave, nod, head shake/tilt, blink, hover, bounce (squash & stretch), shake, sine `oscillate`, `follow_through` (overlapping action down a chain), flash (tint black), fade in/out, pulse, tint. On IK rigs the presets key the IK targets: walk / run plant the feet (constant ground speed, reported for the game), jump squats and tucks, no dead rotation keys |
| **Quality review** | `analyze_animation`: what an animation lead would circle, each with the tool call that fixes it. From the keys: loop pops and hitches, linear (mechanical) motion, dead keys under IK, twinning, limbs without overlap, squash without volume. From the official runtime: per-bone loop gap, single-frame pops, dead holds, foot contacts, foot slide and ground speed. `runtime_sample`: world position / rotation / scale of any bone per frame after IK and physics, plus the events fired |
| **Slot symbols** | `generate_animation` presets `symbol_idle` (rest loop), `symbol_land` (reel stop), `symbol_win` (squeeze, pop, tint-black flash, glow, jelly wobble), `symbol_anticipation` (near-win tease; the tremble snaps to a divisor of the game frame rate, `display_fps` default 30, so it never beats against the frames), `symbol_dim` (darken losers). They start and end on the setup pose so they chain at runtime. On a reel-cell tile they animate the character, not the background / frame (warning otherwise) |
| **Official runtime render** | `runtime_render`: Esoteric's own `spine-webgl` in headless Chromium, so physics, IK, clipping, additive and tint black render exactly as in a web game: PNG, frames, contact sheet, **onion** (ghosted frames + bone trails with one dot per frame: arcs and spacing in one still), GIF, APNG, WebP, MP4, WebM with alpha, MOV ProRes 4444 with alpha. **The tool returns the picture to the assistant** (a contact sheet for animated formats), so it reviews what it made. `debug` draws bones / meshes / clipping / paths over the art, `times` captures key poses, `overlays` + `mix` play other tracks and crossfaded transitions like the game. A sheet keeps at most `max_sheet_frames` cells (24) and warns when it skipped frames; a still asked after the end of a looping clip warns too (use `loop=false` for a held pose). `runtime_validate`: load JSON/.skel + atlas in the official runtime and report what it sees or the exact error |
| **Editor render** | `editor_render`: the Spine editor's own export (reference quality): GIF, APNG, WebM, MOV, AVI or PNG / WebP / JPEG sequences, from a `.spine` or a JSON imported into a throwaway project |
| **Delivery** | `export_web_preview`: one self-contained HTML with the Spine Web Player (animation / skin / background / speed buttons), auto-checked at phone and desktop sizes. `export_game_pack`: `.skel`/`.json` + atlas by the editor, premultiplied alpha, extra resolutions, texture memory report, runtime load check |
| **Preview** | `render_preview`: quick pure-Python PNG frame, contact sheet or GIF (approximate: no constraints or clipping) |
| **Atlas** | `pack_atlas`, `read_atlas`, `unpack_atlas_images` (pure Python; region fields read indented or not, like the official runtime) |
| **Spine CLI** | `spine_status`, `spine_cli_help`, `spine_export` (JSON/binary/+pack/PNG/any settings, clean up, 4.3 `--set` overrides, `target_version` "4.2" JSON downgrade with a list of the 4.3-only features it drops), `spine_import_data` (data → `.spine` project, 4.3 animation import / merge), `spine_pack`, `spine_unpack`, `spine_clean_up`, `spine_project_info`, `spine_last_export_settings`, `write_export_settings`, raw `spine_cli` |
| **Reference** | `spine_reference`: workflow, **quality** (animation principles mapped to tool calls, timing numbers, loop / transition / physics rules), **recipes**, delivery **checklist**, timelines, curves, constraints, presets, 4.3 changes. Also served as MCP resources (`spine://guide/...`) and prompts (`animate`, `review_animation`, `rig_from_psd`) |

The Spine 4.3 format is taken from the official reader (`reference/SkeletonJson.java`, spine-runtimes branch 4.3). The validator accepts every skeleton exported by Spine 4.3 in the official spine-runtimes examples.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Spine 4.3 installed and activated, only for the `spine_*` CLI tools, `editor_render` and `export_game_pack`
- For the official-runtime tools: a headless Chromium (`spine_runtime_setup`, or `uv run playwright install chromium-headless-shell`) and `ffmpeg` for MP4 / WebM / MOV

The Spine web runtimes are **not** vendored: they are under the Spine Runtimes License (every user needs their own Spine Editor license), so on first use the server downloads `@esotericsoftware/spine-webgl` and `spine-player` from npm, checks their sha512 integrity and caches them outside the repository (`SPINE_MCP_CACHE`, default `~/Library/Caches/spine2d-mcp` on macOS). `SPINE_RUNTIME_VERSION` picks the runtime (`4.3`, `4.2`, or exact); by default it follows the data's own version, so a 4.2 export renders with the 4.2 runtime. `SPINE_MCP_GL=software` forces CPU rendering on a machine without GPU.

## Setup

```bash
uv sync
uv run pytest
```

## Use it from Claude Desktop / Claude Code

Add the server to your MCP client configuration (Claude Desktop: *Settings → Developer → Edit config*).

**macOS** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "spine": {
      "command": "uv",
      "args": ["--directory", "/Users/you/code/spine2d-animation-mcp", "run", "spine2d-mcp"],
      "env": {
        "SPINE_EXE": "/Applications/Spine.app/Contents/MacOS/Spine",
        "SPINE_VERSION": "4.3.xx"
      }
    }
  }
}
```

**Windows** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "spine": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\you\\code\\spine2d-animation-mcp", "run", "spine2d-mcp"],
      "env": {
        "SPINE_EXE": "C:\\Program Files\\Spine\\Spine.com",
        "SPINE_VERSION": "4.3.xx"
      }
    }
  }
}
```

If `uv` is not found, use its full path (`which uv` / `where uv`).

**Claude Code**: `claude mcp add spine -- uv --directory /path/to/spine2d-animation-mcp run spine2d-mcp`

### Environment variables

| Variable | Meaning |
|---|---|
| `SPINE_EXE` | Spine executable, install folder or `Spine.app`. Defaults: `C:\Program Files\Spine\Spine.com` (Windows, console build preferred for the CLI), `/Applications/Spine.app/Contents/MacOS/Spine` (macOS), `~/Spine/Spine.sh` (Linux), then `PATH` |
| `SPINE_VERSION` | Editor version passed as `-u` (e.g. `4.3.xx` = latest 4.3 patch, or `4.3.26`) |
| `SPINE_JSON_VERSION` | Version written in `skeleton.spine` of new files (default `4.3.00`) |
| `SPINE_ARGS` | Read by Spine itself (4.3): extra arguments for every run |

## Typical workflow

1. `import_psd_to_spine` on a layered PSD (or `create_skeleton` and build bones/slots yourself), then `runtime_render` with `debug=true` to check the pivots.
2. Rig: IK on legs and arms, physics on hair/tail, meshes where images bend, sliders for facial expressions, clipping, skins.
3. Animate: block the key poses with `set_keyframes` (or `generate_animation` for a base), then curves, `offset_keys` for overlap, `scale_keys` for exaggeration.
4. Review, every time: `analyze_animation`, then `runtime_render` as a sheet on the game's background color and as an onion with `track_bones`; fix and repeat.
5. `runtime_validate`, then `spine_import_data` the JSON into a `.spine` project and open it in Spine 4.3.
6. `export_game_pack` for the game, `editor_render` for presentation videos / GIFs, `export_web_preview` to review on a phone.

Coordinates are Spine's: y-up, relative to the parent bone, rotations in degrees counter-clockwise; bone timeline values are offsets from the setup pose (scale is a multiplier).

## Getting good animation out of it

A valid Spine file is not a good animation. What makes the difference:

- **The assistant must see its work.** A model cannot watch a GIF. `runtime_render` returns a still it can read: a contact sheet (the poses), an onion render (the motion: ghosts, plus the path of each tracked bone with one dot per frame, so close dots = slow, wide dots = fast, and the dotted line is the arc), or a debug render (the rig over the art).
- **Numbers for what a picture can't show.** `analyze_animation` and `runtime_sample` read the motion from the official runtime, after IK and physics: where the loop jumps, which bone pops, whether a foot slides, how fast the ground must move.
- **The method is in the server.** The server instructions tell the assistant to analyze and look after every change; `spine_reference("quality")` maps the animation principles to tool calls with timing numbers; `spine_reference("recipes")` gives key timings for an attack, a walk, an idle, an impact; the `animate` / `review_animation` prompts run the whole loop.
- **Rig for animation first.** Two-bone limbs with IK (knees and elbows), physics on everything loose, meshes with weights where an image bends. A stiff rig cannot be saved by keys.
- **Give the art direction.** Tell the assistant the mood, the weight of the character, the game's background color and the mix duration; ask for the sheet and the onion in the answer.
- **Finish in the editor when it matters.** Weight painting, hand-drawn mesh outlines and the last 10 % of polish on a hero animation are faster by hand: `spine_import_data` gives the project, the keys stay editable.

## Project layout

```
src/spine2d_mcp/
  server.py              stdio entry point
  tools/                 MCP tools (skeleton, animation, quality, render, assets, cli)
  guide.py               working method, quality guide, recipes, checklist (server instructions, spine_reference)
  pipeline.py            PSD -> Spine project orchestration
  psd/                   PSD parsing + body-part conventions
  spine/format.py        4.3 format facts (enums, defaults, timeline layouts)
  spine/validator.py     4.3 structural validation
  spine/document.py      JSON editing with reference/weight/draw order integrity
  spine/attachments.py   attachment builders, grid/polygon meshes, auto weights
  spine/constraints.py   IK / transform / path / physics / slider builders, rig helpers
  spine/animation.py     timelines, keys, curve conversion, sampling, key shifting / scaling
  spine/analysis.py      animation review (key-level and runtime-sampled checks)
  spine/curves.py        easing presets -> Spine bezier curves
  spine/generators.py    procedural animations (IK-aware)
  spine/pose.py          world transforms (all inherit modes)
  spine/preview.py       PNG / sheet / GIF renderer
  spine/schema.py, builder.py, writer.py   typed PSD rig builder
  atlas/                 packer, writer, reader/unpacker
  cli/spine_cli.py       cross-platform Spine CLI wrapper
  runtime/               official spine-webgl in headless Chromium: render, sample, validate, web preview
reference/               SkeletonJson.java (4.3), spineboy.atlas
tests/                   pytest suite
```

## Limits

- `.spine` project files are a private binary format: edit the exported JSON and re-import it (`spine_import_data`).
- The Python preview (`render_preview`) doesn't simulate constraints or clipping; use `runtime_render` or `editor_render`.
- Editor-only work stays in the editor: weight painting, mesh tracing on the image, the graph editor. The server writes the same data (weights, vertices, curves) but without the interactive view.
- `analyze_animation` is a set of heuristics: it says where to look, it does not replace looking at the sheet and the onion render.
- The character presets assume a character facing +x (pass `facing: -1` to walk, or flip the IK `bendPositive`).
- Over a transparent background, additive slots have nothing to add their light to, so glows look missing (Spine behaves the same). Pass `background` with the game's color to judge them; the tool warns.
- Spine 4.3.26's JSON import fails on a curved `rgba` / `rgb` timeline of a tint-black (dark) slot. The server rewrites such timelines as `rgba2` / `rgb2` on save (same look) and says so.
- The 4.3.26 CLI rejects PSD, MP4 and HTML exports; `editor_render` offers the formats that work, `runtime_render` covers MP4.
- CLI flags added late in 4.3 (`-a`, `--merge`, `--set`) depend on your exact editor build: `spine_cli_help` prints the authoritative list.

## License

This project is released under the MIT License.

You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies
of the software, provided that the original copyright notice and license text are
included with substantial portions of the software.

The software is provided "as is", without warranty of any kind. See
[LICENSE](LICENSE) for the full license text.

`reference/SkeletonJson.java` is part of the Spine Runtimes and is covered by the Spine Runtimes License.
