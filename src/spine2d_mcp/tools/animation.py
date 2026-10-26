"""MCP tools: animations (keys, curves, draw order, events, procedural
generators) and previews."""

from __future__ import annotations

import copy
from typing import Any, Literal

from ..spine import animation as an
from ..spine import curves
from ..spine import document as doc
from ..spine import generators as gen
from ..spine import preview
from ._common import editing, mcp, resolve


@mcp.tool()
def manage_animation(
    skeleton: str,
    action: Literal["create", "delete", "rename", "duplicate", "set_color"],
    name: str,
    new_name: str | None = None,
    color: str | None = None,
) -> dict:
    """Create an empty animation, delete, rename (sliders follow), duplicate
    it, or set its dopesheet color (4.3, RRGGBBAA)."""
    with editing(skeleton) as ed:
        anims = doc.animations(ed.data)
        if action == "create":
            if name in anims:
                raise ValueError(f"animation {name!r} already exists")
            anims[name] = {}
            if color:
                anims[name]["color"] = color
        elif name not in anims:
            raise ValueError(f"animation {name!r} not found")
        elif action == "delete":
            for c in ed.data.get("constraints") or []:
                if c.get("type") == "slider" and c.get("animation") == name:
                    raise ValueError(f"slider {c['name']!r} uses animation {name!r}; remove it first")
            del anims[name]
        elif action in ("rename", "duplicate"):
            if not new_name or new_name in anims:
                raise ValueError("new_name is required and must not exist yet")
            if action == "rename":
                ed.data["animations"] = {(new_name if k == name else k): v for k, v in anims.items()}
                for c in ed.data.get("constraints") or []:
                    if c.get("type") == "slider" and c.get("animation") == name:
                        c["animation"] = new_name
            else:
                anims[new_name] = copy.deepcopy(anims[name])
        elif action == "set_color":
            anims[name]["color"] = color
    return ed.result(animations=sorted(doc.animations(ed.data)))


@mcp.tool()
def set_keyframes(
    skeleton: str,
    animation: str,
    kind: Literal["bone", "slot", "ik", "transform", "path", "physics", "slider", "deform", "sequence"],
    target: str,
    keys: list[dict],
    timeline: str | None = None,
    mode: Literal["merge", "replace"] = "merge",
    fps: float | None = None,
) -> dict:
    """Write keyframes on any Spine 4.3 timeline (the animation is created if
    needed). Every key has "time" (seconds) and an optional "curve" to the
    NEXT key: "linear" (default), "stepped", an easing preset ("easeInOut",
    "easeOutBack", "easeInOutSine"... see spine_reference), a normalized
    cubic-bezier [x1, y1, x2, y2], or {"raw": [...]} absolute Spine curve.

    kind / timeline / key values:
    - bone: rotate {value} (degrees, relative to setup), translate {x, y},
      translatex/translatey {value}, scale {x, y} (multiplier), scalex/scaley,
      shear {x, y}, shearx/sheary, inherit {inherit: normal|noScale|...}
    - slot: attachment {name} (null hides), rgba {color: RRGGBBAA}, rgb
      {color: RRGGBB}, alpha {value 0..1}, rgba2 {light: RRGGBBAA, dark:
      RRGGBB} (tint black), rgb2 {light, dark}
    - ik (no timeline): {mix, softness, bendPositive, compress, stretch}
    - transform (no timeline): {mixRotate, mixX, mixY, mixScaleX, mixScaleY, mixShearY}
    - path: position {value}, spacing {value}, mix {mixRotate, mixX, mixY}
    - physics (target "" = all constraints / skeleton wind & gravity): reset
      {} , inertia, strength, damping, mass, wind, gravity, mix {value}
    - slider: time {value}, mix {value}
    - deform (target "skin/slot/attachment" or "slot/attachment"):
      {vertices: [dx, dy, ...] offsets from setup, offset: start index}
    - sequence (same target): {mode: hold|once|loop|pingpong|onceReverse|
      loopReverse|pingpongReverse, index, delay}

    mode "merge" keeps other keys (same time = replaced), "replace" rewrites
    the timeline. fps snaps times to frames (e.g. 30)."""
    with editing(skeleton) as ed:
        anim = doc.animations(ed.data).setdefault(animation, {})
        if kind == "physics" and target == "*":
            target = ""
        _check_target(ed.data, kind, target)
        out = an.set_keys(anim, kind, target, timeline, keys, mode=mode, fps=fps)
        dur = an.animation_duration(anim)
    return ed.result(animation=animation, keys=out, duration=dur)


def _check_target(data: dict, kind: str, target: str) -> None:
    if kind == "bone":
        doc.find_bone(data, target)
    elif kind == "slot":
        doc.find_slot(data, target)
    elif kind in ("ik", "transform", "path", "slider"):
        doc.find_constraint(data, target, kind)
    elif kind == "physics" and target not in ("", "*"):
        doc.find_constraint(data, target, "physics")
    elif kind in ("deform", "sequence"):
        parts = target.split("/")
        if len(parts) == 2:
            parts = ["default", *parts]
        doc.get_attachment(data, parts[1], parts[2], parts[0])


@mcp.tool()
def clear_timeline(
    skeleton: str, animation: str, kind: str, target: str | None = None, timeline: str | None = None,
) -> dict:
    """Delete one timeline (same kind/target/timeline as set_keyframes; kind
    "drawOrder" or "events" need no target)."""
    with editing(skeleton) as ed:
        anim = doc.animations(ed.data).get(animation)
        if anim is None:
            raise ValueError(f"animation {animation!r} not found")
        removed = an.clear_timeline(anim, kind, target, timeline)
    return ed.result(removed=removed)


@mcp.tool()
def set_draw_order_keys(
    skeleton: str,
    animation: str,
    keys: list[dict],
    folder_slots: list[str] | None = None,
    mode: Literal["merge", "replace"] = "merge",
) -> dict:
    """Key the draw order. Each key: {"time", "order": [slot names back to
    front]} or "order": null to go back to the setup order. A partial order
    (subset of slots) only reorders those slots among the positions they
    occupy. Offsets are computed for you.

    4.3 draw order folders: pass `folder_slots` (the slots of one draw-order
    folder) to write a drawOrderFolder timeline that only reorders that folder,
    independently from other folders/tracks."""
    with editing(skeleton) as ed:
        anim = doc.animations(ed.data).setdefault(animation, {})
        if folder_slots:
            for s in folder_slots:
                doc.find_slot(ed.data, s)
            setup = [s for s in doc.slot_names(ed.data) if s in set(folder_slots)]
            out: Any = an.set_draw_order_folder_keys(anim, setup, keys, mode)
        else:
            out = an.set_draw_order_keys(anim, doc.slot_names(ed.data), keys, mode)
    return ed.result(timeline=out)


@mcp.tool()
def add_event_keys(
    skeleton: str, animation: str, keys: list[dict], mode: Literal["merge", "replace"] = "merge",
) -> dict:
    """Fire events: keys [{"time", "name", optional "int", "float", "string",
    "volume", "balance"}]. Undefined events are created with default values."""
    with editing(skeleton) as ed:
        for k in keys:
            if k.get("name") and k["name"] not in (ed.data.get("events") or {}):
                doc.set_event(ed.data, k["name"])
        anim = doc.animations(ed.data).setdefault(animation, {})
        out = an.set_event_keys(anim, keys, mode)
    return ed.result(events=out)


@mcp.tool()
def retime_animation(
    skeleton: str, animation: str, factor: float = 1.0, offset: float = 0.0,
    target_duration: float | None = None,
) -> dict:
    """Speed up / slow down an animation (factor < 1 = faster) or shift it in
    time. target_duration computes the factor for you. Curves are scaled too."""
    with editing(skeleton) as ed:
        anim = doc.animations(ed.data).get(animation)
        if anim is None:
            raise ValueError(f"animation {animation!r} not found")
        if target_duration:
            dur = an.animation_duration(anim)
            if dur <= 0:
                raise ValueError("animation has no keys")
            factor = target_duration / dur
        an.retime(anim, factor, offset)
        dur = an.animation_duration(anim)
    return ed.result(animation=animation, duration=dur, factor=factor)


PRESET_HELP = {
    "idle": "breathing idle (duration, intensity, roles)",
    "walk": "walk cycle (duration, stride, arm_swing, bob, lean, roles)",
    "run": "run cycle (duration, stride, arm_swing, bob, lean, roles)",
    "jump": "anticipation, jump, landing with squash & stretch (duration, height, squash, roles)",
    "wave": "raise an arm and wave (duration, side left|right, raise_angle, waves, roles)",
    "nod": "head nod (duration, amplitude, repeats, roles)",
    "head_shake": "head shake 'no' (duration, amplitude, repeats, roles)",
    "head_tilt": "slow head tilt (duration, amplitude, roles)",
    "blink": "blink via eye bones scaleY or slot attachment swap (duration, blink_time, at, bones | slot, closed_attachment, open_attachment)",
    "hover": "floating bob + tilt on one bone (bone, duration, height, tilt)",
    "bounce": "bouncing with squash & stretch on one bone (bone, duration, height, squash, bounces)",
    "shake": "damped shake / hit reaction / camera shake (bone, duration, intensity, frequency)",
    "oscillate": "sine motion on any bone timeline (bone, timeline, amplitude, period, duration, phase, base, axis, start)",
    "follow_through": "overlapping wave down a chain: tails, hair, capes (bones, amplitude, period, duration, delay, falloff, timeline)",
    "flash": "hit flash via tint black (slots, duration, color, times)",
    "fade_in": "alpha 0 -> 1 (slots, duration)",
    "fade_out": "alpha 1 -> 0 (slots, duration)",
    "pulse": "alpha pulse (slots, duration, times)",
    "tint": "color tint and back (slots, duration, color)",
}


@mcp.tool()
def generate_animation(
    skeleton: str,
    preset: Literal[
        "idle", "walk", "run", "jump", "wave", "nod", "head_shake", "head_tilt", "blink",
        "hover", "bounce", "shake", "oscillate", "follow_through", "flash", "fade_in",
        "fade_out", "pulse", "tint",
    ],
    animation: str | None = None,
    params: dict | None = None,
    mode: Literal["replace", "merge"] = "replace",
) -> dict:
    """Generate a procedural animation with real Spine keys and bezier curves
    (fully editable in the editor). Character presets auto-detect humanoid
    bones (PSD importer names, spineboy-like names...) or take
    params.roles = {"arm_left": "my-bone", ...}. Roles: hip, torso, chest,
    neck, head, arm_/forearm_/hand_/leg_/shin_/foot_ left|right, eye_left,
    eye_right, eyes, tail. mode "merge" adds to an existing animation (layer
    a blink over an idle...). See PRESET_HELP via spine_reference("presets")."""
    p = dict(params or {})
    name = animation or preset
    with editing(skeleton) as ed:
        d = ed.data
        if preset in ("idle", "walk", "run", "jump", "wave"):
            fn = getattr(gen, preset)
            res = fn(d, name=name, mode=mode, **p)
        elif preset in ("nod", "head_shake", "head_tilt"):
            kind = {"nod": "nod", "head_shake": "shake", "head_tilt": "tilt"}[preset]
            res = gen.head_motion(d, name=name, kind=kind, mode=mode, **p)
        elif preset == "blink":
            res = gen.blink(d, name=name, mode=mode, **p)
        elif preset in ("hover", "bounce", "shake"):
            if "bone" not in p:
                raise ValueError(f"{preset} needs params.bone")
            res = getattr(gen, preset)(d, name=name, mode=mode, **p)
        elif preset == "oscillate":
            if "bone" not in p:
                raise ValueError("oscillate needs params.bone")
            if mode == "replace":
                doc.animations(d)[name] = {}
            res = {"keys": gen.oscillate(d, name, **p)}
        elif preset == "follow_through":
            if "bones" not in p:
                raise ValueError("follow_through needs params.bones")
            if mode == "replace":
                doc.animations(d)[name] = {}
            gen.follow_through(d, name, **p)
            res = {"bones": p["bones"]}
        else:
            effect = {"flash": "flash", "fade_in": "fadeIn", "fade_out": "fadeOut",
                      "pulse": "pulse", "tint": "tint"}[preset]
            if "slots" not in p:
                raise ValueError(f"{preset} needs params.slots")
            res = gen.color_effect(d, name=name, effect=effect, mode=mode, **p)
        dur = an.animation_duration(doc.animations(d)[name])
    return ed.result(animation=name, duration=dur, details=res)


@mcp.tool()
def render_preview(
    skeleton: str,
    output: str,
    animation: str | None = None,
    time: float = 0.0,
    mode: Literal["frame", "sheet", "gif"] = "frame",
    frames: int = 8,
    columns: int = 4,
    fps: int = 15,
    width: int = 512,
    height: int = 512,
    skin: str | None = None,
    images_dir: str | None = None,
    atlas: str | None = None,
    show_bones: bool = False,
    background: str | None = "#2b2b2b",
) -> dict:
    """Render the skeleton to an image WITHOUT Spine (pure Python), to check
    a rig or an animation visually: a single frame (setup pose when no
    animation), a contact sheet of `frames` frames, or an animated GIF.
    Images: skeleton.images folder (default), `images_dir`, or a texture
    `atlas` (.atlas next to the JSON is used automatically). Regions, meshes
    (weights, deform), colors and draw order are rendered; constraints and
    clipping are not simulated (use spine_export with PNG settings for an
    exact render)."""
    data = doc.load(resolve(skeleton))
    common = dict(skeleton_path=resolve(skeleton), skin=skin, images_dir=images_dir,
                  atlas_path=atlas, show_bones=show_bones, background=background)
    out = resolve(output)
    if mode == "frame":
        return preview.render(data, out, animation=animation, time=time, size=(width, height), **common)
    if not animation:
        raise ValueError(f"{mode} mode needs an animation")
    if mode == "sheet":
        rows = -(-frames // columns)
        cell = (max(64, width // columns), max(64, height // rows))
        return preview.render_sheet(data, out, animation, frames=frames, columns=columns,
                                    cell=cell, **common)
    return preview.render_gif(data, out, animation, fps=fps, size=(width, height), **common)


@mcp.tool()
def spine_reference(
    topic: Literal["timelines", "curves", "constraints", "presets", "attachments", "workflow", "4.3"] = "workflow",
) -> dict:
    """Cheat sheet of the Spine 4.3 format and of this server's conventions."""
    if topic == "curves":
        return {
            "presets": curves.preset_names(),
            "forms": ["linear", "stepped", "<preset>", "[x1, y1, x2, y2] normalized cubic-bezier",
                      '{"raw": [cx1, cy1, cx2, cy2, ...]} absolute Spine curve'],
            "note": "a key's curve shapes the motion from that key to the next one",
        }
    if topic == "presets":
        return PRESET_HELP
    if topic == "timelines":
        from ..spine import format as fmt

        return {
            "bone": sorted(fmt.BONE_TIMELINES),
            "slot": sorted(fmt.SLOT_TIMELINES),
            "ik": list(fmt.IK_TIMELINE.values) + ["bendPositive", "compress", "stretch"],
            "transform": list(fmt.TRANSFORM_TIMELINE.values),
            "path": sorted(fmt.PATH_TIMELINES),
            "physics": sorted(fmt.PHYSICS_TIMELINES),
            "slider": sorted(fmt.SLIDER_TIMELINES),
            "attachment": ["deform", "sequence"],
            "animation": ["drawOrder", "drawOrderFolder (4.3)", "events", "color (4.3)"],
            "values": "rotate/translate/shear are offsets from the setup pose, scale is a multiplier",
        }
    if topic == "constraints":
        return {
            "order": "4.3: one `constraints` array, array order = update order (update_constraint order_index)",
            "ik": "1-2 bones -> target bone; mix, softness, bendPositive, compress, stretch, scaleY none|uniform|volume",
            "transform": "bones follow source; properties map from->to with offset/scale/max, clamp, localSource, localTarget, additive",
            "path": "bones follow a path attachment; position/spacing modes, rotate tangent|chain|chainScale",
            "physics": "per bone: x/y/rotate/scaleX/shearX amounts, inertia, strength, damping, mass, wind, gravity; scaleY mode",
            "slider": "applies an animation at a time = manual or bone property driven; loop, additive",
        }
    if topic == "attachments":
        return {
            "region": "image; width/height required; optional sequence",
            "mesh": "uvs, triangles, vertices (weighted or not), hull, edges; grid/polygon helpers; optional sequence",
            "linkedmesh": "source mesh (4.3: may be in another slot), skin, timelines",
            "boundingbox": "polygon for hit tests",
            "clipping": "polygon mask until `end` slot; 4.3 inverse + convex",
            "point": "x, y, rotation",
            "path": "bezier path for path constraints; closed, constantSpeed, lengths",
        }
    if topic == "4.3":
        return {
            "new_in_4_3": [
                "sliders (constraint driving an animation, bone property or manual)",
                "transform constraint property mapping, clamp, local/world source & target",
                "volumetric scaleY for IK and physics",
                "draw order folder timelines",
                "inverse and convex clipping",
                "linked meshes from other slots",
                "animation and skin colors, bone icon size/rotation, bone & slot visibility",
                "CLI: import/merge animations & skeletons, --set overrides, wildcards, SPINE_ARGS, --last-export-settings",
                "HTML export (Spine Player / Web Components), atlas per skin, Package Project",
            ],
            "format": "unified `constraints` array with `type`; transform `source` (not target); IK `scaleY` replaces `uniform`; linked mesh `source` (not parent)",
        }
    return {
        "workflow": [
            "1. import_psd_to_spine (layered PSD -> rig + images + atlas) or create_skeleton",
            "2. add/update bones, slots, attachments (region, mesh, clipping...), skins",
            "3. constraints: IK (legs/arms), transform, path, physics (hair/cloth), sliders",
            "4. animations: generate_animation presets, set_keyframes, draw order, events",
            "5. render_preview (frame / sheet / gif) to check visually",
            "6. spine_import_data -> .spine project to open in Spine 4.3",
            "7. spine_export -> runtime JSON/.skel + atlas, PNG/GIF/video via settings",
        ],
        "files": "skeletons are JSON paths; edits are validated and saved atomically",
    }
