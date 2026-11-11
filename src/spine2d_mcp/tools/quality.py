"""MCP tools, prompts and resources for animation QUALITY: the review tool
(`analyze_animation`), the guide as resources, and prompts that walk the
assistant through animating / reviewing the way an animator would."""

from __future__ import annotations

import json

from .. import guide
from ..runtime import render as rt_render
from ..spine import analysis
from ..spine import document as doc
from ._common import READ_ONLY, mcp, resolve


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
    frame), dead_hold (nothing moves), most active bones, peak speed; with
    ground_bones=[foot bones or their IK targets]: the contact intervals,
    foot_slide and the `ground_speed` to move the character at (also the
    times to key footstep events at).

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
                motion = analysis.motion_report(sampled, rep["loop"]["assumed"], physics, ground_bones)
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
