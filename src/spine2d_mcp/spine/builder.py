"""Convert parsed PSD layers into a SpineProject plus an atlas layout.

Coordinate handling (the parts the old prototype got wrong):
- PSD is y-down, top-left origin. Spine is y-up. Convert any PSD point with
  `spine_y = psd_height - psd_y`.
- A bone's x/y in JSON are LOCAL to its parent. With inherit="normal" and no
  rotation in the setup pose, local offset = child_world - parent_world.
  (The old code wrote absolute coords for child bones — a format bug.)
- A bone's pivot is the joint that connects it to its parent, NOT the layer
  center: the edge of the bbox facing the parent (see conventions.joint_side),
  or an explicit `[pivot]` marker. This makes rotation anatomically correct.
- The region attachment is offset from the bone so the image stays put:
  attachment offset = image_center_world - bone_pivot_world.

Draw order (A1): slots are emitted in PSD z-order (bottom-to-top), which is the
Spine draw order — independent of bone creation order.

Virtual bones (A2): intermediate spine bones (hip/torso/chest/neck) with no
layer are created as positioned parents with no slot/attachment, so multi-
segment animations transfer onto skeletons built from sparse PSDs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..atlas.packer import AtlasLayout, Region, pack
from ..psd import conventions as conv
from ..psd.parser import ParsedPsd, PsdLayer
from .schema import Bone, RegionAttachment, Skin, Slot, SpineProject
from .validator import validate


@dataclass
class BuildResult:
    project: SpineProject
    atlas: AtlasLayout
    images: dict[str, PsdLayer]  # region name -> source layer (for atlas paste)


def build(
    parsed: ParsedPsd, max_atlas_size: int = 2048, orient_bones: bool = False
) -> BuildResult:
    """Build the rig. With `orient_bones`, bones point along their body part
    (limbs down, spine/neck/head up) and get a length, like a hand-made rig:
    bones draw along the limbs in the editor and IK constraints work. Without
    it every bone keeps rotation 0 (the original PoC behavior)."""
    # Map canonical part -> layer, keeping each layer's z-index for draw order.
    parts: dict[str, PsdLayer] = {}
    part_z: dict[str, int] = {}
    for z, layer in enumerate(parsed.layers):
        part = conv.canonical_part(layer.name)
        if part is not None and part not in parts:
            parts[part] = layer
            part_z[part] = z

    if not parts:
        raise ValueError(
            "No recognized body-part layers found. Expected names like "
            "head, body, arm_left, leg_right, etc."
        )

    present = set(parts)
    chain = conv.resolve_chain(present)  # includes virtual intermediates

    # World pivots for every bone in the chain (present + virtual).
    world = _compute_pivots(chain, present, parts, parsed)

    rot, length = (
        _orientation(chain, present, parts, world) if orient_bones else ({}, {})
    )

    bones: list[Bone] = [Bone(name=conv.ROOT_BONE)]
    for part in chain:
        parent = conv.parent_of(part)
        px, py = world[part]
        if parent == conv.ROOT_BONE:
            ppx, ppy = 0.0, 0.0
        else:
            ppx, ppy = world[parent]
        prot = rot.get(parent, 0.0)
        lx, ly = _rotate(px - ppx, py - ppy, -prot)
        bones.append(
            Bone(
                name=part,
                parent=parent,
                x=_round(lx),
                y=_round(ly),
                rotation=_round(rot.get(part, 0.0) - prot),
                length=_round(length.get(part, 0.0)),
            )
        )

    # Slots in PSD z-order (draw order); only present parts get a slot.
    slots: list[Slot] = []
    attachments: dict[str, dict[str, RegionAttachment]] = {}
    for part in sorted(present, key=lambda p: part_z[p]):
        layer = parts[part]
        slots.append(Slot(name=part, bone=part, attachment=part))
        # Attachment offset so the image stays where it was in the PSD.
        icx = layer.left + layer.width / 2.0
        icy = parsed.height - (layer.top + layer.height / 2.0)
        bx, by = world[part]
        wr = rot.get(part, 0.0)
        ax, ay = _rotate(icx - bx, icy - by, -wr)
        attachments[part] = {
            part: RegionAttachment(
                width=float(layer.width),
                height=float(layer.height),
                x=_round(ax),
                y=_round(ay),
                rotation=_round(-wr),
            )
        }

    project = SpineProject(
        bones=bones,
        slots=slots,
        skins=[Skin(name="default", attachments=attachments)],
    )
    project.skeleton.width = float(parsed.width)
    project.skeleton.height = float(parsed.height)

    validate(project)

    regions = [
        Region(name=part, width=parts[part].width, height=parts[part].height)
        for part in present
    ]
    atlas = pack(regions, max_size=max_atlas_size)
    return BuildResult(
        project=project,
        atlas=atlas,
        images={part: parts[part] for part in present},
    )


def _round(v: float) -> float:
    v = round(v, 4)
    return 0.0 if v == 0 else v


def _rotate(x: float, y: float, deg: float) -> tuple[float, float]:
    if not deg:
        return x, y
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c - y * s, x * s + y * c


# World direction a part extends in, from the side its joint is on.
_SIDE_ROTATION = {"top": -90.0, "bottom": 90.0, "left": 0.0, "right": 180.0}


def _orientation(
    chain: list[str],
    present: set[str],
    parts: dict[str, PsdLayer],
    world: dict[str, tuple[float, float]],
) -> tuple[dict[str, float], dict[str, float]]:
    """World rotation and length per bone for an oriented rig."""
    rot: dict[str, float] = {}
    length: dict[str, float] = {}
    for part in chain:
        side = conv.joint_side(part)
        layer = parts.get(part)
        if side is not None:
            rot[part] = _SIDE_ROTATION[side]
            if layer is not None:
                length[part] = float(
                    layer.height if side in ("top", "bottom") else layer.width
                )
            continue
        # Spine chain (hip/torso/chest): point up toward the next bone.
        rot[part] = 90.0
        kids = [c for c in chain if conv.parent_of(c) == part]
        up = [c for c in kids if c in ("torso", "chest", "neck", "head")]
        if up:
            cx, cy = world[up[0]]
            px, py = world[part]
            d = math.hypot(cx - px, cy - py)
            if d > 1e-6:
                rot[part] = math.degrees(math.atan2(cy - py, cx - px))
                length[part] = d
                continue
        if layer is not None:
            length[part] = layer.height / 2.0
    return rot, length


def _compute_pivots(
    chain: list[str],
    present: set[str],
    parts: dict[str, PsdLayer],
    parsed: ParsedPsd,
) -> dict[str, tuple[float, float]]:
    """World-space (Spine y-up) pivot for each bone in the chain."""
    world: dict[str, tuple[float, float]] = {}
    for part in chain:
        if part in present:
            world[part] = _part_pivot(part, parts[part], parsed)
    # Virtual intermediates: place between nearest present ancestor and the
    # average of present direct descendants (or ancestor if none).
    for part in chain:
        if part in world:
            continue
        world[part] = _virtual_pivot(part, chain, world, parsed)
    return world


def _part_pivot(
    part: str, layer: PsdLayer, parsed: ParsedPsd
) -> tuple[float, float]:
    # Explicit marker wins.
    if part in parsed.pivot_markers:
        mx, my = parsed.pivot_markers[part]
        return mx, parsed.height - my

    side = conv.joint_side(part)
    cx = layer.left + layer.width / 2.0
    if side is None:
        cy = layer.top + layer.height / 2.0
        return cx, parsed.height - cy
    # PSD y-down: "top" edge is layer.top, "bottom" edge is layer.top+height.
    if side == "top":
        cy = layer.top
    elif side == "bottom":
        cy = layer.top + layer.height
    elif side == "left":
        cx, cy = layer.left, layer.top + layer.height / 2.0
    elif side == "right":
        cx, cy = layer.left + layer.width, layer.top + layer.height / 2.0
    else:
        cy = layer.top + layer.height / 2.0
    return cx, parsed.height - cy


def _virtual_pivot(
    part: str,
    chain: list[str],
    world: dict[str, tuple[float, float]],
    parsed: ParsedPsd,
) -> tuple[float, float]:
    # Nearest present ancestor.
    anc = conv.parent_of(part)
    while anc != conv.ROOT_BONE and anc not in world:
        anc = conv.parent_of(anc)
    anc_pt = world.get(anc)

    # Present direct children of this part.
    children = [
        c for c in chain if conv.parent_of(c) == part and c in world
    ]
    if children:
        cx = sum(world[c][0] for c in children) / len(children)
        cy = sum(world[c][1] for c in children) / len(children)
        if anc_pt is not None:
            return (anc_pt[0] + cx) / 2.0, (anc_pt[1] + cy) / 2.0
        return cx, cy
    if anc_pt is not None:
        return anc_pt
    return parsed.width / 2.0, parsed.height / 2.0
