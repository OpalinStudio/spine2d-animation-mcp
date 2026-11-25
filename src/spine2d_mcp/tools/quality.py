"""MCP tools, prompts and resources for QUALITY: the art review before the
rig (`check_art`, `clean_art`), the animation review (`analyze_animation`),
the guide as resources, and prompts that walk the assistant through the work
the way an animator would."""

from __future__ import annotations

import io
import json
from pathlib import Path

from mcp.server.fastmcp import Image as McpImage

from .. import guide
from ..runtime import render as rt_render
from ..spine import analysis, art
from ..spine import document as doc
from ._common import READ_ONLY, mcp, resolve


class _Parts:
    """Image source for the preview renderer backed by loaded images."""

    def __init__(self, images: dict):
        self.images = images

    def get(self, path: str):
        return self.images.get(path)


def _picture(img) -> McpImage:
    k = min(1.0, 1568 / max(img.size))
    if k < 1:
        img = img.resize((round(img.width * k), round(img.height * k)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return McpImage(data=buf.getvalue(), format="jpeg")


def _skeleton_images(path: Path, data: dict) -> str:
    """Where the skeleton's art is: its images folder, else its atlas."""
    rel = (data.get("skeleton") or {}).get("images")
    for d in ([path.parent / rel] if rel else []) + [path.parent / "images"]:
        if d.is_dir():
            return str(d)
    atlas = rt_render.find_atlas(path)
    if atlas is None:
        raise ValueError("no images folder and no .atlas next to the skeleton: pass `images`")
    return str(atlas)


@mcp.tool(structured_output=False, annotations=READ_ONLY)
def check_art(
    images: str | None = None,
    skeleton: str | None = None,
    skin: str | None = None,
    names: list[str] | None = None,
    joint_angle: float = 25,
    return_image: bool = True,
):
    """Quality control of the ART, to run BEFORE rigging (and again once the
    skeleton exists): a rig cannot fix a bad cut-out. `images` is a folder of
    PNG / WebP parts, one image, or a .atlas; with only `skeleton`, its images
    folder (or atlas) is used. `names` limits the check to some parts.

    Per part: hard_edges (opaque -> transparent with no antialiasing: stair
    steps), frayed_edges (spikes / torn outline left by the cut-out),
    fragments (detached leftovers), light_fringe (halo of the removed
    background), see_through (semi-transparent inside), several_pieces,
    cut_by_border, soft_art (blurrier than the other parts).
    With `skeleton`: upscaled / stretched (image drawn larger than its pixels)
    and joint_gap: every joint is bent by +/- joint_angle degrees and the
    hole that opens is measured (parts cut edge to edge with nothing drawn
    underneath; joints bridged by a weighted mesh are skipped).

    Each finding says how to fix it: clean_art repairs hard edges and
    fragments without touching the drawing; the others need the part to be
    redrawn / regenerated (the `fix` text is the instruction to give). The
    result carries a sheet of the flagged parts with the defects painted on
    (red = hard outline, magenta = frayed, yellow box = fragment, cyan =
    fringe) and, with a skeleton, the setup pose with the open joints
    circled: LOOK at them. Do not rig a part that has warnings."""
    data = None
    if skeleton:
        sk_path = resolve(skeleton)
        data = doc.load(sk_path)
        images = images or _skeleton_images(sk_path, data)
    if not images:
        raise ValueError("pass `images` (folder, file or .atlas) and / or `skeleton`")
    parts = art.load_images(images, names)
    reports = art.check_images(parts)
    attachments = art.check_attachments(data, parts) if data else []
    joints = art.check_joints(data, _Parts(parts), skin, joint_angle) if data else []

    flagged = []
    infos: dict[str, list[str]] = {}
    for r in reports:
        warnings = [i for i in r["issues"] if i["severity"] == "warning"]
        for i in r["issues"]:
            if i["severity"] != "warning":
                infos.setdefault(i["code"], []).append(r["name"])
        if warnings:
            flagged.append({"part": r["name"], "size": r["metrics"]["size"],
                            "issues": [{k: v for k, v in i.items() if k != "severity"} for i in warnings]})
    n_warn = sum(len(f["issues"]) for f in flagged) + len(attachments) + len(joints)
    out = {
        "source": str(resolve(images)),
        "checked": len(parts),
        "parts_with_warnings": len(flagged),
        "warnings": n_warn,
        "parts": flagged,
        "worth_a_look": {code: names_ for code, names_ in sorted(infos.items())},
        **({"attachments": attachments, "joints": [{k: v for k, v in j.items() if k not in ("severity", "pivot_px", "radius_px")}
                                                    for j in joints]} if data else {}),
        "verdict": (
            "fix before rigging: clean_art for hard_edges / fragments, regenerate the parts with "
            "frayed_edges / light_fringe / joint_gap (the `fix` text is the brief)" if n_warn else
            "no defect measured: check the sheet with your eyes, then rig"),
    }
    if not return_image:
        return out
    pictures = []
    sheet = art.annotate(parts, reports)
    if sheet is not None:
        pictures.append(_picture(sheet))
    if joints:
        pictures.append(_picture(art.joints_overview(data, _Parts(parts), joints, skin)))
    return [out, *pictures]


@mcp.tool()
def clean_art(
    images: str,
    out_dir: str,
    names: list[str] | None = None,
    fragments: bool = True,
    soften: float | None = None,
    smooth: float = 0,
    bleed: int = 8,
    overwrite: bool = False,
) -> dict:
    """Repair cut-out defects WITHOUT changing the drawing, its size or its
    position, so the parts stay valid for an existing rig. `images`: a folder
    (recursive) or one image; the cleaned PNGs are written to `out_dir` with
    the same names (pass overwrite=true to write over the originals).

    fragments: erase detached leftovers (pieces under 3 % of the main one).
    soften: antialias the outline by this radius in px, inwards only; None =
    0.8 px where check_art finds hard_edges, nothing elsewhere. smooth: trim
    spikes thinner than this many px (0 = off; it also trims drawn fur or
    whiskers: look at the result). bleed: spread the art's colours this many
    px under the transparent rim so no engine pulls black or white into the
    outline when it filters the texture.
    It does not fix a torn edge, a halo of the old background, a missing
    overlap at a joint or a blurry part: those must be redrawn. Returns what
    was done per part and the warnings left; run check_art on `out_dir`."""
    src = resolve(images)
    dst = resolve(out_dir)
    if dst == (src if src.is_dir() else src.parent) and not overwrite:
        raise ValueError("out_dir is the source folder: pass overwrite=true to replace the originals")
    parts = art.load_images(src, names)
    dst.mkdir(parents=True, exist_ok=True)
    done = []
    left = 0
    for name, img in parts.items():
        cleaned, what = art.clean_image(img, fragments, soften, smooth, bleed)
        target = dst / f"{name}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        cleaned.save(target)
        after = [i["code"] for i in art.check_image(cleaned, name)["issues"] if i["severity"] == "warning"]
        left += len(after)
        if set(what) - {"bleed_px"} or after:
            done.append({"part": name, **{k: v for k, v in what.items() if k != "bleed_px"},
                         **({"still": after} if after else {})})
    return {"out_dir": str(dst), "written": len(parts), "changed": done, "warnings_left": left,
            "note": "same sizes and positions as the originals: the skeleton does not change"}


def _physics_bones(data: dict) -> set[str]:
    """Bones moved by physics, and everything below them."""
    out: set[str] = set()
    for c in data.get("constraints") or []:
        if c.get("type") == "physics" and c.get("bone"):
            out |= {c["bone"], *doc.descendants(data, c["bone"])}
    return out


@mcp.tool(annotations=READ_ONLY)
def analyze_animation(
    skeleton: str,
    animation: str | None = None,
    loop: bool | None = None,
    runtime: bool = True,
    ground_bones: list[str] | None = None,
    fps: float = 60,
) -> dict:
    """Review an animation like an animation lead would (all animations when
    `animation` is omitted) and list what to fix, each with the tool call
    that fixes it. Run it after every animation change, before rendering.

    From the keys: loop_pop (last value != first), loop_hitch (speed break
    at the loop point), linear_motion (no easing: mechanical), stepped_motion,
    dead_keys (rotation keys overridden by an IK constraint), twinning (left
    and right identical), no_overlap (a limb keyed as one rigid piece),
    squash_volume, spin, key_soup.
    From the OFFICIAL runtime (runtime=true; IK and physics applied): loop_gap
    (pose at the end vs the start, per bone), pop (a bone jumping in one
    frame), dead_hold (nothing moves), most active bones, peak speed,
    `amplitude` (share of the drawn bones that move, their average range in
    % of the character's size, largest rotation; timid_motion when most of
    the character stays frozen); with ground_bones=[foot bones or their IK
    targets]: the contact intervals, foot_slide and the `ground_speed` to
    move the character at (also the times to key footstep events at).

    loop: true / false, or None to detect it (most timelines end where they
    start). severity: warning = visible defect, info = worth a look. The
    checks are heuristics that tell you where to LOOK: still render a sheet
    and an onion (runtime_render) and judge with your eyes."""
    path = resolve(skeleton)
    data = doc.load(path)
    names = [animation] if animation else sorted(doc.animations(data))
    if not names:
        raise ValueError("the skeleton has no animation")
    physics = _physics_bones(data)
    reports = []
    for name in names:
        rep = analysis.analyze(data, name, loop)
        if runtime and rep["duration"] > 0:
            try:
                sampled = rt_render.sample(str(path), name, fps=fps, loop=False, include_last=True)
                motion = analysis.motion_report(sampled, rep["loop"]["assumed"], physics, ground_bones,
                                                {s["bone"] for s in doc.slots(data)})
                if sampled["events"]:
                    motion["events_fired"] = sampled["events"]
            except (rt_render.RuntimeRenderError, OSError) as e:
                motion = {"issues": [], "runtime_error": str(e)[:400]}
            rep["issues"] += motion.pop("issues")
            rep["motion"] = motion
            rep["counts"] = {s: sum(1 for i in rep["issues"] if i["severity"] == s)
                             for s in analysis.SEVERITIES}
        rep["verdict"] = (
            "fix the warnings, then look at a sheet and an onion render" if rep["counts"]["warning"]
            or rep["counts"]["error"] else
            "no defect detected by the checks: now judge poses, arcs and timing on a sheet and "
            "an onion render")
        reports.append(rep)
    return reports[0] if animation else {"skeleton": str(path), "animations": reports}


# ----------------------------------------------------------------- guide
@mcp.resource("spine://guide/workflow", mime_type="application/json")
def guide_workflow() -> str:
    """The working method, step by step, with the tool for each step."""
    return json.dumps(guide.WORKFLOW, indent=2)


@mcp.resource("spine://guide/quality", mime_type="application/json")
def guide_quality() -> str:
    """Animation principles mapped to tool calls, timing numbers, game rules, physics tuning."""
    return json.dumps(guide.QUALITY, indent=2)


@mcp.resource("spine://guide/recipes", mime_type="application/json")
def guide_recipes() -> str:
    """Ready-made key timings: attack, walk, idle, impact, pop, bending meshes, expressions."""
    return json.dumps(guide.RECIPES, indent=2)


@mcp.resource("spine://guide/checklist", mime_type="application/json")
def guide_checklist() -> str:
    """What to verify before delivering an animation."""
    return json.dumps(guide.CHECKLIST, indent=2)


@mcp.resource("spine://guide/art", mime_type="application/json")
def guide_art() -> str:
    """How the parts must be designed, split, drawn or generated to be animated."""
    return json.dumps(guide.ART, indent=2)


_LOOP = (
    "Work in passes and LOOK at each one (runtime_render returns the picture):\n"
    "1. inspect_skeleton, then runtime_render format=\"png\" debug=true to learn the rig.\n"
    "2. Read spine_reference(\"quality\") and the matching entry of spine_reference(\"recipes\").\n"
    "3. Block the key poses (set_keyframes, or generate_animation as a base). Render a sheet "
    "with times=[the key pose times] on the game's background and fix the silhouettes.\n"
    "4. Add curves on every moving segment, overlapping action (offset_keys stagger), "
    "exaggeration (scale_keys), physics on loose parts, draw order and events.\n"
    "5. analyze_animation and fix every warning.\n"
    "6. runtime_render format=\"sheet\", then format=\"onion\" with track_bones on the hands, "
    "feet and head: arcs must be smooth, spacing must ease. Correct and repeat 5-6 until you "
    "would sign it.\n"
    "7. Test the transition from / to the neighbouring animation (overlays on track 0 with mix).\n"
    "8. runtime_validate, then tell me what you made, what you checked, and what still needs "
    "an animator's hand in the Spine editor."
)


@mcp.prompt()
def animate(skeleton: str, brief: str) -> str:
    """Create a new animation to a brief, with the full review loop."""
    return (f"Animate the Spine skeleton `{skeleton}`.\nBrief: {brief}\n\n{_LOOP}")


@mcp.prompt()
def review_animation(skeleton: str, animation: str) -> str:
    """Critique and improve an existing animation."""
    return (
        f"Review and improve the animation `{animation}` of `{skeleton}`.\n"
        "1. analyze_animation on it (give ground_bones if it is a walk / run).\n"
        "2. runtime_render format=\"sheet\" and format=\"onion\" (track_bones: hands, feet, head) "
        "on the game's background; look at both.\n"
        "3. List the defects against spine_reference(\"checklist\"), most visible first.\n"
        "4. Fix them with the smallest edits (set_keyframes mode=\"merge\", offset_keys, "
        "scale_keys, physics); keep the timing I approved unless it is the problem.\n"
        "5. Re-run 1-2 and show before / after."
    )


@mcp.prompt()
def prepare_art(character: str, images_dir: str) -> str:
    """Produce (or repair) the parts of a character so they can be animated."""
    return (
        f"Prepare the art of this character for Spine animation: {character}\n"
        f"Parts folder: `{images_dir}`\n"
        "1. Read spine_reference(\"art\"). List the parts the character needs: limb segments, "
        "hand poses, head parts, loose parts, props, effects.\n"
        "2. Generate a character sheet in a neutral pose first, then ONE image per part with "
        "the sheet as reference: the part alone, complete with its hidden rounded ends, same "
        "line weight and palette, transparent background.\n"
        "3. check_art on the folder and LOOK at the annotated sheet. clean_art for hard_edges "
        "and fragments. Regenerate every part that keeps a warning, quoting its `fix` text in "
        "the request. Repeat until check_art has no warning.\n"
        "4. Rig, then check_art(skeleton=...): regenerate the parts named by joint_gap with "
        "the longer hidden end it asks for.\n"
        "5. Report the parts produced, what was regenerated and why, and what still needs a "
        "human artist."
    )


@mcp.prompt()
def rig_from_psd(psd_path: str) -> str:
    """Turn a layered PSD into an animation-ready rig."""
    return (
        f"Build an animation-ready Spine rig from `{psd_path}`.\n"
        "1. import_psd_to_spine (ik_legs / ik_arms for a character). Layers named head, body, "
        "arm_left, forearm_left, hand_left, leg_left, shin_left, foot_left... become the "
        "humanoid rig; other layers get their own bone (inside a `head` group they follow the "
        "head; a `[bone]` group makes a bone; `[ignore]` skips).\n"
        "2. runtime_render format=\"png\" debug=true: check every pivot sits on its joint; fix "
        "with update_bone (keep_world_position) or `<part>[pivot]` marker layers.\n"
        "3. Add what the art needs: meshes + weights where images must bend, physics on hair / "
        "cloth / tails, clipping, skins.\n"
        "4. Prove the rig with generate_animation idle and walk, analyze_animation and a sheet.\n"
        "5. runtime_validate, then spine_import_data to produce the .spine project."
    )
