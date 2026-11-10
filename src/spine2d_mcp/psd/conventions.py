"""Layer-name conventions and skeleton topology of the PSD importer.

A layer named after a known body part maps to a bone + slot + region
attachment. Bones follow a fixed, anatomically multi-segment hierarchy so the
procedural animations (idle, walk, run, jump...) apply to any imported
character.

Intermediate bones (hip/torso/chest/neck) may have no corresponding layer; they
are still created as *virtual* bones when needed as a parent of a present part
(see `resolve_chain`). Forearms and shins are optional segments: when absent,
hands hang off the arm and feet off the leg.

Everything else is kept too: any other layer becomes its own bone + slot +
image (parented to the body part whose group it is in, else to root), a group
tagged `[bone]` becomes a bone for the layers inside it, and `[ignore]` skips
a layer or group. So a PSD that is not a humanoid (a slot-game symbol, a prop,
a creature) imports as well.
"""

from __future__ import annotations

ROOT_BONE = "root"

# part -> parent. Order = bone creation order (parent precedes child).
# Multi-segment torso: root -> hip -> torso -> chest -> neck -> head.
# Limbs hang off chest; legs off hip.
BODY_HIERARCHY: dict[str, str] = {
    "hip": ROOT_BONE,
    "torso": "hip",
    "chest": "torso",
    "neck": "chest",
    "head": "neck",
    "arm_left": "chest",
    "arm_right": "chest",
    "forearm_left": "arm_left",
    "forearm_right": "arm_right",
    "hand_left": "forearm_left",
    "hand_right": "forearm_right",
    "leg_left": "hip",
    "leg_right": "hip",
    "shin_left": "leg_left",
    "shin_right": "leg_right",
    "foot_left": "shin_left",
    "foot_right": "shin_right",
}

# Bones that are structural only — created virtually if absent as layers.
INTERMEDIATE_BONES = {"hip", "torso", "chest", "neck"}

# Limb segments that are skipped (not created virtually) when the PSD has no
# layer for them: their child attaches to the segment above.
OPTIONAL_SEGMENTS = {"forearm_left", "forearm_right", "shin_left", "shin_right"}

# Accepted aliases -> canonical part name. A single `body` layer maps to torso.
_ALIASES: dict[str, str] = {
    "body": "torso",
    "chest_body": "chest",
    "pelvis": "hip",
    **{
        f"{alias}_{side}": f"{part}_{side}"
        for side in ("left", "right")
        for alias, part in (
            ("upper_arm", "arm"), ("lower_arm", "forearm"), ("thigh", "leg"),
            ("upper_leg", "leg"), ("lower_leg", "shin"), ("calf", "shin"),
        )
    },
}

# Side of a part's bbox that faces its parent joint (the pivot edge).
# "top": pivot at top edge midpoint (y-up max), "bottom": bottom edge, etc.
# Limbs/extremities pivot at the end nearest the body; head pivots at its base.
_JOINT_SIDE: dict[str, str] = {
    "head": "bottom",
    "neck": "bottom",
    "arm_left": "top",
    "arm_right": "top",
    "forearm_left": "top",
    "forearm_right": "top",
    "hand_left": "top",
    "hand_right": "top",
    "leg_left": "top",
    "leg_right": "top",
    "shin_left": "top",
    "shin_right": "top",
    "foot_left": "top",
    "foot_right": "top",
}

# Marker suffix for an explicit pivot override layer, e.g. "arm_left[pivot]".
PIVOT_TAG = "[pivot]"
# A group with this tag becomes a bone; a layer or group with IGNORE_TAG is skipped.
BONE_TAG = "[bone]"
IGNORE_TAG = "[ignore]"


def canonical_part(layer_name: str) -> str | None:
    """Canonical body-part name for a layer, or None if unrecognized."""
    key = normalize(layer_name)
    if key in BODY_HIERARCHY:
        return key
    return _ALIASES.get(key)


def pivot_marker_key(layer_name: str) -> str | None:
    """If the layer is a pivot-override marker (`<name>[pivot]`), return what
    it overrides: the canonical part, or the normalized name of any other
    layer / `[bone]` group; else None."""
    raw = layer_name.strip().lower()
    if not raw.endswith(PIVOT_TAG):
        return None
    base = raw[: -len(PIVOT_TAG)].strip()
    return canonical_part(base) or normalize(base)


def strip_tags(name: str) -> str:
    """The name without the `[bone]` / `[ignore]` tags."""
    low = name.lower()
    for tag in (BONE_TAG, IGNORE_TAG):
        i = low.find(tag)
        while i >= 0:
            name, low = name[:i] + name[i + len(tag):], low[:i] + low[i + len(tag):]
            i = low.find(tag)
    return name.strip()


def parent_of(part: str, present: set[str] | None = None) -> str:
    """Parent bone of a body part. With `present`, optional limb segments
    (forearm, shin) that have no layer are skipped."""
    parent = BODY_HIERARCHY[part]
    while present is not None and parent in OPTIONAL_SEGMENTS and parent not in present:
        parent = BODY_HIERARCHY[parent]
    return parent


def joint_side(part: str) -> str | None:
    """Bbox edge facing the parent, or None to fall back to bbox center
    (used for the torso/root area where no single joint dominates)."""
    return _JOINT_SIDE.get(part)


def resolve_chain(present_parts: set[str]) -> list[str]:
    """All bones needed in creation order, including virtual intermediates.

    A bone is included if it is present, or if it is an intermediate ancestor
    of a present bone. Result is ordered so every bone's parent precedes it.
    """
    needed: set[str] = set()
    for part in present_parts:
        needed.add(part)
        cur = part
        while True:
            par = parent_of(cur, present_parts)
            if par == ROOT_BONE:
                break
            needed.add(par)
            cur = par
    return [p for p in BODY_HIERARCHY if p in needed]


def normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")
