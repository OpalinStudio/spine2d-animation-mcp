"""MCP tools: skeleton structure (bones, slots, skins, attachments,
constraints, events)."""

from __future__ import annotations

import copy
from typing import Any, Literal

from ..spine import attachments as att
from ..spine import constraints as cons
from ..spine import document as doc
from ..spine.validator import validate_data
from ._common import drop_none, editing, mcp, resolve

# ------------------------------------------------------------------ files


@mcp.tool()
def create_skeleton(
    skeleton: str,
    width: float = 0,
    height: float = 0,
    images: str | None = "./images/",
    audio: str | None = None,
    fps: float | None = None,
    reference_scale: float | None = None,
    overwrite: bool = False,
) -> dict:
    """Create a new, empty Spine 4.3 skeleton JSON (root bone + default skin).

    Args:
        skeleton: Path of the .json file to create.
        width/height: Skeleton bounds (informational, used by the editor).
        images: Images folder, relative to the JSON (where `<attachment path>.png` live).
        audio: Audio folder for audio events.
        fps: Dopesheet frames per second (editor default 30).
        reference_scale: Physics reference scale (default 100).
        overwrite: Replace an existing file.
    """
    path = resolve(skeleton)
    if path.exists() and not overwrite:
        raise ValueError(f"{path} exists (pass overwrite=true to replace it)")
    data = doc.new_skeleton(width, height, images=images, audio=audio, fps=fps,
                            reference_scale=reference_scale)
    doc.save(data, path)
    return {"skeleton": str(path), "spine_version": data["skeleton"]["spine"]}


@mcp.tool()
def inspect_skeleton(
    skeleton: str,
    section: Literal["summary", "full", "bones", "slots", "constraints", "skins", "events", "animations"] = "summary",
) -> dict:
    """Read a skeleton: a compact summary (bones tree, slots/draw order,
    constraints, skins, events, animations with durations), the full JSON, or
    one section of it."""
    data = doc.load(resolve(skeleton))
    if section == "summary":
        return doc.summary(data)
    if section == "full":
        return data
    if section == "animations":
        return {"animations": data.get("animations") or {}}
    return {section: data.get(section) or ([] if section != "events" else {})}


@mcp.tool()
def validate_skeleton(skeleton: str) -> dict:
    """Check a skeleton JSON against the Spine 4.3 reader rules (references,
    required fields, enums, weighted vertices, curves, draw order offsets...).
    Works on files exported by the Spine editor too."""
    return validate_data(doc.load(resolve(skeleton))).as_dict()


@mcp.tool()
def get_element(
    skeleton: str,
    kind: Literal["bone", "slot", "constraint", "skin", "attachment", "animation", "event"],
    name: str,
    slot: str | None = None,
    skin: str = "default",
    constraint_type: str | None = None,
) -> dict:
    """Return the raw JSON of one element. For attachments pass `slot` (and
    `skin`)."""
    data = doc.load(resolve(skeleton))
    if kind == "bone":
        return doc.find_bone(data, name)
    if kind == "slot":
        return doc.find_slot(data, name)
    if kind == "constraint":
        return doc.find_constraint(data, name, constraint_type)
    if kind == "skin":
        return doc.find_skin(data, name)
    if kind == "attachment":
        if not slot:
            raise ValueError("attachment lookup needs `slot`")
        return doc.get_attachment(data, slot, name, skin)
    if kind == "animation":
        anims = data.get("animations") or {}
        if name not in anims:
            raise ValueError(f"animation {name!r} not found")
        return anims[name]
    events = data.get("events") or {}
    if name not in events:
        raise ValueError(f"event {name!r} not found")
    return events[name]


# ------------------------------------------------------------------ bones


@mcp.tool()
def add_bone(
    skeleton: str,
    name: str,
    parent: str | None = None,
    x: float = 0,
    y: float = 0,
    rotation: float = 0,
    length: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    shear_x: float = 0,
    shear_y: float = 0,
    inherit: Literal["normal", "onlyTranslation", "noRotationOrReflection", "noScale", "noScaleOrReflection"] = "normal",
    color: str | None = None,
    icon: str | None = None,
    icon_size: float | None = None,
    icon_rotation: float | None = None,
    visible: bool = True,
    skin_required: bool = False,
    world: bool = False,
) -> dict:
    """Add a bone. Position/rotation are relative to the parent (Spine local
    space, y-up) unless `world=true`, then x/y/rotation are world (setup pose)
    values converted to local. Parent defaults to the root bone.

    color: RRGGBBAA editor color. icon/icon_size/icon_rotation (4.3): bone
    icon shown in the editor. skin_required: bone only active when a skin
    listing it is active (add it to a skin with update_skin)."""
    with editing(skeleton) as ed:
        fields = dict(
            length=length, x=x, y=y, rotation=rotation, scaleX=scale_x, scaleY=scale_y,
            shearX=shear_x, shearY=shear_y, inherit=inherit, color=color, icon=icon,
            iconSize=icon_size, iconRotation=icon_rotation, visible=visible, skin=skin_required,
        )
        bone = doc.add_bone(ed.data, name, parent=parent, **fields)
        if world:
            from ..spine.pose import Pose

            pose = Pose(ed.data)
            p = pose.bones[bone["parent"]]
            lx, ly = p.world_to_local(x, y)
            doc.update_bone(ed.data, name, x=lx, y=ly, rotation=rotation - p.world_rotation)
    return ed.result(bone=doc.find_bone(ed.data, name))


@mcp.tool()
def update_bone(
    skeleton: str,
    name: str,
    new_name: str | None = None,
    parent: str | None = None,
    keep_world_position: bool = True,
    x: float | None = None,
    y: float | None = None,
    rotation: float | None = None,
    length: float | None = None,
    scale_x: float | None = None,
    scale_y: float | None = None,
    shear_x: float | None = None,
    shear_y: float | None = None,
    inherit: str | None = None,
    color: str | None = None,
    icon: str | None = None,
    icon_size: float | None = None,
    icon_rotation: float | None = None,
    visible: bool | None = None,
    skin_required: bool | None = None,
) -> dict:
    """Change a bone's setup pose / properties, rename it (every reference is
    updated) or reparent it (keeps its on-screen transform by default).
    Only the given fields change."""
    with editing(skeleton) as ed:
        if parent is not None and parent != doc.find_bone(ed.data, name).get("parent"):
            doc.reparent_bone(ed.data, name, parent, keep_world=keep_world_position)
        doc.update_bone(
            ed.data, name, x=x, y=y, rotation=rotation, length=length, scaleX=scale_x,
            scaleY=scale_y, shearX=shear_x, shearY=shear_y, inherit=inherit, color=color,
            icon=icon, iconSize=icon_size, iconRotation=icon_rotation, visible=visible,
            skin=skin_required,
        )
        if new_name:
            doc.rename_bone(ed.data, name, new_name)
    return ed.result(bone=doc.find_bone(ed.data, new_name or name))


@mcp.tool()
def remove_bone(skeleton: str, name: str) -> dict:
    """Remove a bone with its children, their slots/attachments, the
    constraints that depend on them and their animation timelines."""
    with editing(skeleton) as ed:
        removed = doc.remove_bone(ed.data, name)
    return ed.result(**removed)


# ------------------------------------------------------------------ slots


@mcp.tool()
def add_slot(
    skeleton: str,
    name: str,
    bone: str,
    attachment: str | None = None,
    color: str | None = None,
    dark_color: str | None = None,
    blend: Literal["normal", "additive", "multiply", "screen"] = "normal",
    visible: bool = True,
    index: int | None = None,
) -> dict:
    """Add a slot (draw order entry) on a bone. `attachment` is the setup
    attachment name; `index` is the draw order position (0 = back, default
    front). color RRGGBBAA tint; dark_color RRGGBB enables tint black."""
    with editing(skeleton) as ed:
        doc.add_slot(ed.data, name, bone, index=index, attachment=attachment, color=color,
                     dark=dark_color, blend=blend, visible=visible)
    return ed.result(slot=doc.find_slot(ed.data, name), draw_order=doc.slot_names(ed.data))


@mcp.tool()
def update_slot(
    skeleton: str,
    name: str,
    new_name: str | None = None,
    bone: str | None = None,
    attachment: str | None = None,
    color: str | None = None,
    dark_color: str | None = None,
    blend: str | None = None,
    visible: bool | None = None,
) -> dict:
    """Change a slot (pass attachment="" to clear the setup attachment) or
    rename it (references, timelines and draw order keys follow)."""
    with editing(skeleton) as ed:
        doc.update_slot(ed.data, name, bone=bone, attachment=attachment, color=color,
                        dark=dark_color, blend=blend, visible=visible)
        if new_name:
            doc.rename_slot(ed.data, name, new_name)
    return ed.result(slot=doc.find_slot(ed.data, new_name or name))


@mcp.tool()
def remove_slot(skeleton: str, name: str) -> dict:
    """Remove a slot, its attachments in every skin and its timelines (draw
    order keys are re-encoded)."""
    with editing(skeleton) as ed:
        doc.remove_slot(ed.data, name)
    return ed.result(draw_order=doc.slot_names(ed.data))


@mcp.tool()
def set_draw_order(skeleton: str, order: list[str]) -> dict:
    """Set the setup-pose draw order: every slot name, back to front.
    Existing draw order animation keys are re-encoded to keep their look."""
    with editing(skeleton) as ed:
        doc.set_setup_draw_order(ed.data, order)
    return ed.result(draw_order=doc.slot_names(ed.data))


# ------------------------------------------------------------ attachments


def _put(ed, slot: str, name: str, a: dict, skin: str, make_setup: bool) -> dict:
    doc.set_attachment(ed.data, slot, name, a, skin=skin, make_setup=make_setup)
    return {"slot": slot, "skin": skin, "attachment": name, "data": a}


@mcp.tool()
def add_region_attachment(
    skeleton: str,
    slot: str,
    name: str,
    width: float,
    height: float,
    x: float = 0,
    y: float = 0,
    rotation: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    path: str | None = None,
    color: str | None = None,
    skin: str = "default",
    make_setup: bool = True,
    sequence_count: int | None = None,
    sequence_start: int = 1,
    sequence_digits: int = 0,
    sequence_setup: int = 0,
) -> dict:
    """Add a region (image) attachment. x/y/rotation place the image center in
    the slot bone's space. `path` is the image name if it differs from the
    attachment name (images/<path>.png or atlas region).
    Image sequences (frame-by-frame): sequence_count frames named
    <path><start..> zero-padded to sequence_digits; key them with
    set_keyframes kind="sequence"."""
    a = att.region(width, height, x, y, rotation, scale_x, scale_y, path=path, color=color,
                   sequence_count=sequence_count, sequence_start=sequence_start,
                   sequence_digits=sequence_digits, sequence_setup=sequence_setup)
    with editing(skeleton) as ed:
        res = _put(ed, slot, name, a, skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def add_mesh_attachment(
    skeleton: str,
    slot: str,
    name: str,
    mode: Literal["grid", "polygon", "explicit"] = "grid",
    width: float | None = None,
    height: float | None = None,
    x: float = 0,
    y: float = 0,
    cols: int = 4,
    rows: int = 4,
    outline: list[list[float]] | None = None,
    uvs: list[float] | None = None,
    triangles: list[int] | None = None,
    vertices: list[float] | None = None,
    hull: int | None = None,
    edges: list[int] | None = None,
    path: str | None = None,
    color: str | None = None,
    skin: str = "default",
    make_setup: bool = True,
    weight_bones: list[str] | None = None,
    sequence_count: int | None = None,
) -> dict:
    """Add a mesh attachment (deformable image).

    mode "grid": cols x rows grid over a width x height image centered at
    (x, y) in bone space; ideal for squash/stretch, breathing, cloth, faces.
    mode "polygon": `outline` = silhouette points in IMAGE pixels (origin top
    left), triangulated automatically; image of width x height centered at (x, y).
    mode "explicit": give uvs (0..1, origin top-left), triangles, vertices
    (unweighted x,y pairs or Spine weighted layout), hull, edges.
    weight_bones: bind the mesh to these bones with automatic weights (so it
    bends with them), e.g. a tail or arm chain."""
    if mode == "grid":
        if not width or not height:
            raise ValueError("grid mode needs width and height")
        a = att.grid_mesh(width, height, cols, rows, x, y, path=path, color=color)
    elif mode == "polygon":
        if not outline or not width or not height:
            raise ValueError("polygon mode needs outline, width and height")
        a = att.polygon_mesh(outline, width, height, x, y, path=path)
        if color:
            a["color"] = color
    else:
        if uvs is None or triangles is None or vertices is None:
            raise ValueError("explicit mode needs uvs, triangles and vertices")
        a = att.mesh(uvs, triangles, vertices, hull, edges, width, height, path=path, color=color)
    if sequence_count:
        a["sequence"] = {"count": sequence_count}
    with editing(skeleton) as ed:
        if weight_bones:
            a["vertices"] = att.auto_weights(ed.data, slot, a, weight_bones)
        res = _put(ed, slot, name, a, skin, make_setup)
    return ed.result(**{k: v for k, v in res.items() if k != "data"},
                     vertex_count=len(a["uvs"]) // 2, triangles=len(a["triangles"]) // 3,
                     weighted=bool(weight_bones))


@mcp.tool()
def bind_mesh_weights(
    skeleton: str,
    slot: str,
    attachment: str,
    bones: list[str],
    skin: str = "default",
    max_influences: int = 4,
    falloff: float = 2.0,
) -> dict:
    """Bind an unweighted mesh (or bounding box / clipping / path) to bones
    with automatic weights based on distance to each bone segment (setup
    pose). Like the editor's Auto weights; refine weights in Spine if needed."""
    with editing(skeleton) as ed:
        a = doc.get_attachment(ed.data, slot, attachment, skin)
        a["vertices"] = att.auto_weights(ed.data, slot, a, bones, max_influences, falloff)
    return ed.result(attachment=attachment, bones=bones)


@mcp.tool()
def add_linked_mesh(
    skeleton: str,
    slot: str,
    name: str,
    source: str,
    source_skin: str | None = None,
    source_slot: str | None = None,
    inherit_timelines: bool = True,
    path: str | None = None,
    width: float | None = None,
    height: float | None = None,
    skin: str = "default",
    make_setup: bool = False,
) -> dict:
    """Linked mesh: reuse `source` mesh geometry and weights with another
    image (skins, outfits). 4.3: the source may be in another slot
    (`source_slot`). inherit_timelines: also use the source's deform keys."""
    a = att.linked_mesh(source, source_skin, source_slot, inherit_timelines, width, height, path)
    with editing(skeleton) as ed:
        res = _put(ed, slot, name, a, skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def add_bounding_box(
    skeleton: str, slot: str, name: str, points: list[list[float]],
    skin: str = "default", make_setup: bool = True, color: str | None = None,
) -> dict:
    """Bounding box (hit area / collision polygon), points in bone space."""
    with editing(skeleton) as ed:
        res = _put(ed, slot, name, att.bounding_box(points, color), skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def add_clipping_attachment(
    skeleton: str, slot: str, name: str, points: list[list[float]],
    end_slot: str | None = None, inverse: bool = False, convex: bool = False,
    skin: str = "default", make_setup: bool = True, color: str | None = None,
) -> dict:
    """Clipping mask polygon (bone space). Clips every slot drawn after it up
    to `end_slot`. 4.3: `inverse` hides what is INSIDE the polygon, `convex`
    declares the polygon convex for faster clipping."""
    with editing(skeleton) as ed:
        a = att.clipping(points, end_slot, convex, inverse, color)
        res = _put(ed, slot, name, a, skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def add_point_attachment(
    skeleton: str, slot: str, name: str, x: float = 0, y: float = 0, rotation: float = 0,
    skin: str = "default", make_setup: bool = True,
) -> dict:
    """Point attachment (spawn point for bullets, particles, effects)."""
    with editing(skeleton) as ed:
        res = _put(ed, slot, name, att.point(x, y, rotation), skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def add_path_attachment(
    skeleton: str, slot: str, name: str, points: list[Any], closed: bool = False,
    constant_speed: bool = True, skin: str = "default", make_setup: bool = True,
) -> dict:
    """Bezier path (for path constraints: tank treads, snakes, ropes, motion
    paths). points: [x, y] (smooth handles computed) or {"x","y","in":[x,y],
    "out":[x,y]} with absolute handles, in bone space."""
    with editing(skeleton) as ed:
        a = att.path(points, closed, constant_speed)
        res = _put(ed, slot, name, a, skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def set_attachment_raw(
    skeleton: str, slot: str, name: str, attachment: dict, skin: str = "default",
    make_setup: bool = False,
) -> dict:
    """Write any attachment JSON as-is (advanced: copy from an export, custom
    fields). It is validated against the 4.3 rules before saving."""
    with editing(skeleton) as ed:
        res = _put(ed, slot, name, copy.deepcopy(attachment), skin, make_setup)
    return ed.result(**res)


@mcp.tool()
def update_attachment(
    skeleton: str, slot: str, name: str, fields: dict, skin: str = "default",
) -> dict:
    """Merge fields into an existing attachment (e.g. {"x": 10, "rotation":
    -5}, {"inverse": true}, {"sequence": {"count": 8}}). A null value removes
    the field."""
    with editing(skeleton) as ed:
        a = doc.get_attachment(ed.data, slot, name, skin)
        for k, v in fields.items():
            if v is None:
                a.pop(k, None)
            else:
                a[k] = v
    return ed.result(attachment=a)


@mcp.tool()
def remove_attachment(skeleton: str, slot: str, name: str, skin: str = "default") -> dict:
    """Remove an attachment from a skin (and its deform/sequence keys)."""
    with editing(skeleton) as ed:
        doc.remove_attachment(ed.data, slot, name, skin)
    return ed.result(removed=name)


# ------------------------------------------------------------------ skins


@mcp.tool()
def add_skin(
    skeleton: str, name: str, color: str | None = None, copy_from: str | None = None,
    bones: list[str] | None = None, constraints: list[dict] | None = None,
) -> dict:
    """Create a skin (optionally a copy of another one). bones / constraints
    ({"name", "type"}) become skin-required: active only with this skin."""
    with editing(skeleton) as ed:
        if copy_from:
            doc.duplicate_skin(ed.data, copy_from, name)
            doc.update_skin(ed.data, name, color=color, add_bones=bones, add_constraints=constraints)
        else:
            doc.add_skin(ed.data, name, color, bones, constraints)
    return ed.result(skin=doc.find_skin(ed.data, name))


@mcp.tool()
def update_skin(
    skeleton: str, name: str, new_name: str | None = None, color: str | None = None,
    add_bones: list[str] | None = None, remove_bones: list[str] | None = None,
    add_constraints: list[dict] | None = None, remove_constraints: list[dict] | None = None,
) -> dict:
    """Rename a skin, set its color, or add/remove skin bones and skin
    constraints ({"name": ..., "type": "ik|transform|path|physics|slider"})."""
    with editing(skeleton) as ed:
        doc.update_skin(ed.data, name, color, add_bones, remove_bones, add_constraints, remove_constraints)
        if new_name:
            doc.rename_skin(ed.data, name, new_name)
    return ed.result(skin=doc.find_skin(ed.data, new_name or name))


@mcp.tool()
def remove_skin(skeleton: str, name: str) -> dict:
    """Delete a skin (not the default one)."""
    with editing(skeleton) as ed:
        doc.remove_skin(ed.data, name)
    return ed.result(removed=name)


# ------------------------------------------------------------ constraints


@mcp.tool()
def add_ik_constraint(
    skeleton: str,
    bones: list[str],
    name: str | None = None,
    target: str | None = None,
    create_target: bool = False,
    target_parent: str | None = None,
    mix: float = 1.0,
    softness: float = 0.0,
    bend_positive: bool = True,
    compress: bool = False,
    stretch: bool = False,
    scale_y: Literal["none", "uniform", "volume"] = "none",
    skin_required: bool = False,
    index: int | None = None,
) -> dict:
    """IK constraint on 1 or 2 bones (arm/leg/aim). With create_target=true a
    target bone is created at the chain's end (bone tip or first child),
    parented to target_parent (default root). 4.3 scale_y: with
    compress/stretch, "uniform" keeps the aspect ratio, "volume" squashes and
    stretches preserving area."""
    with editing(skeleton) as ed:
        if create_target:
            res = cons.ik_for_chain(ed.data, bones, target_name=target, target_parent=target_parent,
                                    constraint_name=name, bend_positive=bend_positive, mix=mix,
                                    softness=softness, compress=compress, stretch=stretch,
                                    scale_y=scale_y, skin=skin_required)
            c = res["constraint"]
            if index is not None:
                doc.move_constraint(ed.data, c["name"], index, "ik")
        else:
            if not target:
                raise ValueError("pass target, or create_target=true")
            c = cons.ik(name or f"{bones[-1]}-ik", bones, target, mix, softness, bend_positive,
                        compress, stretch, scale_y, skin_required)
            doc.add_constraint(ed.data, c, index)
    return ed.result(constraint=c)


@mcp.tool()
def add_transform_constraint(
    skeleton: str,
    name: str,
    source: str,
    bones: list[str],
    copy: list[str] | None = None,
    properties: dict | None = None,
    mix_rotate: float = 1.0,
    mix_x: float = 1.0,
    mix_y: float | None = None,
    mix_scale_x: float = 1.0,
    mix_scale_y: float | None = None,
    mix_shear_y: float = 1.0,
    offsets: dict | None = None,
    local_source: bool = False,
    local_target: bool = False,
    additive: bool = False,
    clamp: bool = False,
    skin_required: bool = False,
    index: int | None = None,
) -> dict:
    """4.3 transform constraint: the constrained `bones` follow the `source`
    bone.

    copy: properties copied 1:1 (rotate, x, y, scaleX, scaleY, shearY);
    default all six. properties: full 4.3 mapping where one property drives
    another, e.g. {"rotate": {"to": {"scaleY": {"scale": 0.01}}}} (rotating
    the source scales the bones), {"x": {"offset": 0, "to": {"rotate":
    {"scale": 0.5, "max": 45}}}}; with clamp=true `max` limits the result.
    offsets: {"rotation","x","y","scaleX","scaleY","shearY"} added to the
    constrained values. local_source/local_target: use local instead of
    world space. additive: add to the bones' own transform."""
    o = offsets or {}
    c = cons.transform(
        name, source, bones, properties=properties,
        copy=copy if copy is not None else ("rotate", "x", "y", "scaleX", "scaleY", "shearY"),
        mix_rotate=mix_rotate, mix_x=mix_x, mix_y=mix_y, mix_scale_x=mix_scale_x,
        mix_scale_y=mix_scale_y, mix_shear_y=mix_shear_y,
        offset_rotation=o.get("rotation", 0), offset_x=o.get("x", 0), offset_y=o.get("y", 0),
        offset_scale_x=o.get("scaleX", 0), offset_scale_y=o.get("scaleY", 0),
        offset_shear_y=o.get("shearY", 0), local_source=local_source, local_target=local_target,
        additive=additive, clamp=clamp, skin=skin_required,
    )
    with editing(skeleton) as ed:
        doc.add_constraint(ed.data, c, index)
    return ed.result(constraint=c)


@mcp.tool()
def add_path_constraint(
    skeleton: str,
    name: str,
    slot: str,
    bones: list[str],
    position_mode: Literal["fixed", "percent"] = "percent",
    spacing_mode: Literal["length", "fixed", "percent", "proportional"] = "length",
    rotate_mode: Literal["tangent", "chain", "chainScale"] = "tangent",
    position: float = 0,
    spacing: float = 0,
    offset_rotation: float = 0,
    mix_rotate: float = 1.0,
    mix_x: float = 1.0,
    mix_y: float | None = None,
    skin_required: bool = False,
    index: int | None = None,
) -> dict:
    """Path constraint: `bones` follow the path attachment shown in `slot`
    (add one with add_path_attachment). Animate `position` to move along."""
    c = cons.path(name, slot, bones, position_mode, spacing_mode, rotate_mode, offset_rotation,
                  position, spacing, mix_rotate, mix_x, mix_y, skin_required)
    with editing(skeleton) as ed:
        doc.add_constraint(ed.data, c, index)
    return ed.result(constraint=c)


@mcp.tool()
def add_physics_constraint(
    skeleton: str,
    bones: list[str],
    name: str | None = None,
    x: float = 0,
    y: float = 0,
    rotate: float = 1.0,
    scale_x: float = 0,
    shear_x: float = 0,
    scale_y: Literal["none", "uniform", "volume"] = "none",
    inertia: float = 0.5,
    strength: float = 100,
    damping: float = 0.85,
    mass: float = 1.0,
    wind: float = 0,
    gravity: float = 0,
    mix: float = 1.0,
    limit: float = 5000,
    fps: int = 60,
    global_properties: list[str] | None = None,
    chain_falloff: float = 0.15,
    skin_required: bool = False,
) -> dict:
    """Physics (secondary motion: hair, cloth, tails, breasts, belly, ears,
    antennae, jiggle). One constraint per bone; for several bones (a chain)
    later bones get more inertia and less strength (`chain_falloff`).
    x/y/rotate/scale_x/shear_x: 0..1 amount of each simulated property.
    4.3 scale_y: "uniform"/"volume" make scaleY follow the simulated scaleX
    (volume = squash & stretch). global_properties: use the skeleton-wide
    values (keyed on physics target "") for inertia/strength/damping/mass/
    wind/gravity/mix."""
    with editing(skeleton) as ed:
        if len(bones) == 1:
            c = cons.physics(name or f"{bones[0]}-physics", bones[0], x, y, rotate, scale_x, shear_x,
                             scale_y, limit, fps, inertia, strength, damping, mass, wind, gravity,
                             mix, tuple(global_properties or ()), skin_required)
            doc.add_constraint(ed.data, c)
            out = [c]
        else:
            out = cons.physics_chain(
                ed.data, bones, name_prefix=name, rotate=rotate, x=x, y=y, inertia=inertia,
                strength=strength, damping=damping, mass=mass, gravity=gravity, wind=wind,
                falloff=chain_falloff, scale_x=scale_x, shear_x=shear_x, scale_y=scale_y,
                limit=limit, fps=fps, mix=mix, global_=tuple(global_properties or ()),
                skin=skin_required,
            )
    return ed.result(constraints=out)


@mcp.tool()
def add_slider(
    skeleton: str,
    name: str,
    animation: str,
    bone: str | None = None,
    property: Literal["rotate", "x", "y", "scaleX", "scaleY", "shearY"] | None = None,
    from_value: float = 0,
    to_time: float = 0,
    scale: float = 1,
    max_value: float = 0,
    local: bool = False,
    time: float = 0,
    mix: float = 1,
    loop: bool = False,
    additive: bool = False,
    skin_required: bool = False,
    index: int | None = None,
) -> dict:
    """4.3 slider constraint: applies `animation` (a pose library / blend
    shape / facial expression) at a time that is either manual (`time`, keyed
    with set_keyframes kind="slider" timeline "time") or driven by a bone
    property: time = to_time + (bone.property - from_value) * scale.
    Example: a "smile" animation driven by a control bone's y translation:
    bone="face-ctrl", property="y", scale=1/50 (50px = 1s of animation).
    loop: wrap time; additive: add on top of the current pose; max_value:
    editor slider range."""
    c = cons.slider(name, animation, bone, property, from_value, to_time, scale, max_value, local,
                    time, mix, loop, additive, skin_required)
    with editing(skeleton) as ed:
        if animation not in doc.animations(ed.data):
            doc.animations(ed.data)[animation] = {}
        doc.add_constraint(ed.data, c, index)
    return ed.result(constraint=c)


@mcp.tool()
def update_constraint(
    skeleton: str,
    name: str,
    fields: dict,
    constraint_type: str | None = None,
    new_name: str | None = None,
    order_index: int | None = None,
) -> dict:
    """Change constraint fields using 4.3 JSON names (e.g. {"mix": 0.5},
    {"bendPositive": false}, {"scaleY": "volume"}, {"strength": 150},
    {"properties": {...}}), rename it, or move it in the update order
    (`order_index`, 0 = updated first)."""
    with editing(skeleton) as ed:
        c = doc.update_constraint(ed.data, name, constraint_type, **fields)
        if new_name:
            doc.rename_constraint(ed.data, name, new_name, c["type"])
        if order_index is not None:
            doc.move_constraint(ed.data, new_name or name, order_index, c["type"])
    return ed.result(constraint=c, order=[f"{x['type']}:{x['name']}" for x in ed.data.get("constraints", [])])


@mcp.tool()
def remove_constraint(skeleton: str, name: str, constraint_type: str | None = None) -> dict:
    """Remove a constraint, its skin entries and its animation timelines."""
    with editing(skeleton) as ed:
        doc.remove_constraint(ed.data, name, constraint_type)
    return ed.result(removed=name)


# ----------------------------------------------------------------- events


@mcp.tool()
def set_event(
    skeleton: str,
    name: str,
    int_value: int | None = None,
    float_value: float | None = None,
    string_value: str | None = None,
    audio: str | None = None,
    volume: float | None = None,
    balance: float | None = None,
    new_name: str | None = None,
) -> dict:
    """Create or update an event definition (footsteps, hit frames, sounds).
    audio: file relative to the skeleton's audio folder; volume 0..1;
    balance -1 (left) .. 1 (right). Key events with add_event_keys."""
    with editing(skeleton) as ed:
        doc.set_event(ed.data, name, **drop_none({
            "int": int_value, "float": float_value, "string": string_value,
            "audio": audio, "volume": volume, "balance": balance,
        }))
        if new_name:
            doc.rename_event(ed.data, name, new_name)
    return ed.result(event=(ed.data.get("events") or {}).get(new_name or name))


@mcp.tool()
def remove_event(skeleton: str, name: str) -> dict:
    """Delete an event definition and all its keys."""
    with editing(skeleton) as ed:
        doc.remove_event(ed.data, name)
    return ed.result(removed=name)
