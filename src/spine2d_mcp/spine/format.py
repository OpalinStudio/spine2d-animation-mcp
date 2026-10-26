"""Spine 4.3 skeleton JSON format facts, in one place.

Everything here is transcribed from the canonical 4.3 reader
`reference/SkeletonJson.java` (spine-runtimes branch 4.3): field names, enum
values, defaults and the value layout of every timeline. The validator, the
document editor, the curve helpers and the preview renderer all read from
these tables so they can't drift apart.

Main 4.3 changes vs 4.2 that matter for writers:
- A single top-level `constraints` array replaces `ik`/`transform`/`path`/
  `physics`. Each entry has a `type` (`ik`, `transform`, `path`, `physics`,
  `slider`) and the array order IS the update order (no `order` field).
- New `slider` constraint (drives an animation from a bone property or a
  manual `time`), keyed with `slider` timelines (`time`, `mix`).
- Transform constraints map properties: `properties: {from: {offset, to: {to:
  {offset, max, scale}}}}`, plus `localSource`, `localTarget`, `additive`,
  `clamp`. The source bone is `source` (was `target`).
- IK and physics have `scaleY` mode: `none` | `uniform` | `volume`.
- Clipping has `convex` and `inverse`; linked meshes may reference a source
  mesh in another `slot`; `drawOrderFolder` animation timelines.
- Bones gained `icon`, `iconSize`, `iconRotation`, `visible`; slots `visible`;
  animations and skins a `color`.
"""

from __future__ import annotations

import os

# Version stamped into `skeleton.spine`. The editor uses major.minor to pick its
# reader; the patch only matters for a "newer version" warning, so default to
# the first 4.3 release. Override with SPINE_JSON_VERSION (e.g. "4.3.26").
DEFAULT_SPINE_VERSION = "4.3.00"


def spine_version() -> str:
    return os.environ.get("SPINE_JSON_VERSION", DEFAULT_SPINE_VERSION)


INHERIT_MODES = (
    "normal",
    "onlyTranslation",
    "noRotationOrReflection",
    "noScale",
    "noScaleOrReflection",
)
BLEND_MODES = ("normal", "additive", "multiply", "screen")
SCALE_Y_MODES = ("none", "uniform", "volume")
POSITION_MODES = ("fixed", "percent")
SPACING_MODES = ("length", "fixed", "percent", "proportional")
ROTATE_MODES = ("tangent", "chain", "chainScale")
ATTACHMENT_TYPES = (
    "region",
    "boundingbox",
    "mesh",
    "linkedmesh",
    "path",
    "point",
    "clipping",
)
SEQUENCE_MODES = (
    "hold",
    "once",
    "loop",
    "pingpong",
    "onceReverse",
    "loopReverse",
    "pingpongReverse",
)
CONSTRAINT_TYPES = ("ik", "transform", "path", "physics", "slider")
# Transform constraint / slider property names (from and to).
TRANSFORM_PROPERTIES = ("rotate", "x", "y", "scaleX", "scaleY", "shearY")

# Skin -> constraint list keys, one per constraint type.
SKIN_CONSTRAINT_KEYS = {
    "ik": "ik",
    "transform": "transform",
    "path": "path",
    "physics": "physics",
    "slider": "slider",
}

# Bone setup-pose fields and their reader defaults.
BONE_DEFAULTS = {
    "parent": None,
    "length": 0.0,
    "x": 0.0,
    "y": 0.0,
    "rotation": 0.0,
    "scaleX": 1.0,
    "scaleY": 1.0,
    "shearX": 0.0,
    "shearY": 0.0,
    "inherit": "normal",
    "skin": False,
    "color": None,
    "icon": None,
    "iconSize": 1.0,
    "iconRotation": 0.0,
    "visible": True,
}

SLOT_DEFAULTS = {
    "color": None,
    "dark": None,
    "attachment": None,
    "blend": "normal",
    "visible": True,
}

IK_DEFAULTS = {
    "skin": False,
    "scaleY": None,
    "mix": 1.0,
    "softness": 0.0,
    "bendPositive": True,
    "compress": False,
    "stretch": False,
}

TRANSFORM_DEFAULTS = {
    "skin": False,
    "localSource": False,
    "localTarget": False,
    "additive": False,
    "clamp": False,
    "rotation": 0.0,
    "x": 0.0,
    "y": 0.0,
    "scaleX": 0.0,
    "scaleY": 0.0,
    "shearY": 0.0,
    "mixRotate": 1.0,
    "mixX": 1.0,
    "mixScaleX": 1.0,
    "mixShearY": 1.0,
    # mixY defaults to mixX, mixScaleY to mixScaleX: handled specially.
}

PATH_DEFAULTS = {
    "skin": False,
    "positionMode": "percent",
    "spacingMode": "length",
    "rotateMode": "tangent",
    "rotation": 0.0,
    "position": 0.0,
    "spacing": 0.0,
    "mixRotate": 1.0,
    "mixX": 1.0,
}

PHYSICS_DEFAULTS = {
    "skin": False,
    "x": 0.0,
    "y": 0.0,
    "rotate": 0.0,
    "scaleX": 0.0,
    "scaleY": None,
    "shearX": 0.0,
    "limit": 5000.0,
    "fps": 60,
    "inertia": 0.5,
    "strength": 100.0,
    "damping": 0.85,
    "mass": 1.0,
    "wind": 0.0,
    "gravity": 0.0,
    "mix": 1.0,
    "inertiaGlobal": False,
    "strengthGlobal": False,
    "dampingGlobal": False,
    "massGlobal": False,
    "windGlobal": False,
    "gravityGlobal": False,
    "mixGlobal": False,
}

SLIDER_DEFAULTS = {
    "skin": False,
    "additive": False,
    "loop": False,
    "mix": 1.0,
    "time": 0.0,
    "from": 0.0,
    "to": 0.0,
    "scale": 1.0,
    "max": 0.0,
    "local": False,
}

CONSTRAINT_DEFAULTS = {
    "ik": IK_DEFAULTS,
    "transform": TRANSFORM_DEFAULTS,
    "path": PATH_DEFAULTS,
    "physics": PHYSICS_DEFAULTS,
    "slider": SLIDER_DEFAULTS,
}


class TimelineSpec:
    """Value layout of one timeline type.

    `values` lists the per-key numeric fields in the order the reader feeds
    them to `readCurve` (= the order of the 4-number groups in a bezier
    `curve` array). `defaults` are the reader defaults for those fields.
    A spec with `curve=False` has no curves (attachment, inherit, events...).
    `kind` tells how values are stored: "num" (plain fields), "color" (hex
    color fields split into channels).
    """

    def __init__(
        self,
        values: tuple[str, ...] = (),
        defaults: tuple[float, ...] = (),
        curve: bool = True,
        kind: str = "num",
        color_fields: tuple[tuple[str, int], ...] = (),
        default_from: dict[str, str] | None = None,
    ):
        self.values = values
        self.defaults = defaults
        self.curve = curve
        self.kind = kind
        # For color timelines: (json field, channel count) in curve order.
        self.color_fields = color_fields
        # Value whose default is another value of the same key (mixY -> mixX).
        self.default_from = default_from or {}

    @property
    def value_count(self) -> int:
        if self.kind == "color":
            return sum(n for _, n in self.color_fields)
        return len(self.values)


_V = ("value",)

BONE_TIMELINES: dict[str, TimelineSpec] = {
    "rotate": TimelineSpec(_V, (0.0,)),
    "translate": TimelineSpec(("x", "y"), (0.0, 0.0)),
    "translatex": TimelineSpec(_V, (0.0,)),
    "translatey": TimelineSpec(_V, (0.0,)),
    "scale": TimelineSpec(("x", "y"), (1.0, 1.0)),
    "scalex": TimelineSpec(_V, (1.0,)),
    "scaley": TimelineSpec(_V, (1.0,)),
    "shear": TimelineSpec(("x", "y"), (0.0, 0.0)),
    "shearx": TimelineSpec(_V, (0.0,)),
    "sheary": TimelineSpec(_V, (0.0,)),
    "inherit": TimelineSpec(curve=False),
}

SLOT_TIMELINES: dict[str, TimelineSpec] = {
    "attachment": TimelineSpec(curve=False),
    "rgba": TimelineSpec(kind="color", color_fields=(("color", 4),)),
    "rgb": TimelineSpec(kind="color", color_fields=(("color", 3),)),
    "alpha": TimelineSpec(_V, (0.0,)),
    "rgba2": TimelineSpec(kind="color", color_fields=(("light", 4), ("dark", 3))),
    "rgb2": TimelineSpec(kind="color", color_fields=(("light", 3), ("dark", 3))),
}

IK_TIMELINE = TimelineSpec(("mix", "softness"), (1.0, 0.0))

TRANSFORM_TIMELINE = TimelineSpec(
    ("mixRotate", "mixX", "mixY", "mixScaleX", "mixScaleY", "mixShearY"),
    (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    default_from={"mixY": "mixX"},
)

PATH_TIMELINES: dict[str, TimelineSpec] = {
    "position": TimelineSpec(_V, (0.0,)),
    "spacing": TimelineSpec(_V, (0.0,)),
    "mix": TimelineSpec(
        ("mixRotate", "mixX", "mixY"), (1.0, 1.0, 1.0), default_from={"mixY": "mixX"}
    ),
}

PHYSICS_TIMELINES: dict[str, TimelineSpec] = {
    "reset": TimelineSpec(curve=False),
    "inertia": TimelineSpec(_V, (0.0,)),
    "strength": TimelineSpec(_V, (0.0,)),
    "damping": TimelineSpec(_V, (0.0,)),
    "mass": TimelineSpec(_V, (0.0,)),
    "wind": TimelineSpec(_V, (0.0,)),
    "gravity": TimelineSpec(_V, (0.0,)),
    "mix": TimelineSpec(_V, (1.0,)),
}

SLIDER_TIMELINES: dict[str, TimelineSpec] = {
    "time": TimelineSpec(_V, (1.0,)),
    "mix": TimelineSpec(_V, (1.0,)),
}

# Deform curves interpolate a 0..1 blend between the two keys' vertices.
DEFORM_TIMELINE = TimelineSpec(("__blend",), (0.0,))
SEQUENCE_TIMELINE = TimelineSpec(curve=False)


def constraint_timeline_specs(ctype: str) -> dict[str, TimelineSpec]:
    """Timelines keyed under `animations.<anim>.<ctype>.<constraint>`.

    IK and transform constraints have a single anonymous timeline (the key
    list sits directly under the constraint name), represented here as "".
    """
    if ctype == "ik":
        return {"": IK_TIMELINE}
    if ctype == "transform":
        return {"": TRANSFORM_TIMELINE}
    if ctype == "path":
        return PATH_TIMELINES
    if ctype == "physics":
        return PHYSICS_TIMELINES
    if ctype == "slider":
        return SLIDER_TIMELINES
    raise ValueError(f"unknown constraint type {ctype!r}")


# Top-level keys of an animation object.
ANIMATION_KEYS = (
    "slots",
    "bones",
    "ik",
    "transform",
    "path",
    "physics",
    "slider",
    "attachments",
    "drawOrder",
    "drawOrderFolder",
    "events",
    "color",
)
