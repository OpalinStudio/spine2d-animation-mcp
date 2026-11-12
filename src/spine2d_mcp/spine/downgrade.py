"""What a 4.3 skeleton loses when it is exported to an older JSON/binary
version (Spine export settings `version`, e.g. "4.2").

The editor only prints "Exporting ... from 4.3 to 4.2 may lose information"
and then "Complete": nothing says WHAT is lost. Esoteric lists the 4.3-only
features dropped by such an export (https://esotericsoftware.com/forum/d/30848):
sliders and their keys, transform constraint property mapping, draw order
folders and their keys, inverse clipping, linked meshes whose source mesh is
in another slot, and the volume scale mode of IK / physics. A slider exported
to 4.2 lands in a top-level `slider` key that the 4.2 reader ignores, so a
pose held by it reverts to setup with no error (probe: 4.3.26 editor, render
in spine-webgl 4.2.85).

Everything here reads plain dicts in the 4.3 layout of
`reference/SkeletonJson.java`; nothing is written.
"""

from __future__ import annotations

import re
from typing import Any

# Top-level keys the 4.2 JSON reader understands (spine-runtimes 4.2
# SkeletonJson.readSkeletonData). Anything else in a "-from-" export is ignored.
KEYS_42 = ("skeleton", "bones", "slots", "ik", "transform", "path", "physics", "skins", "events", "animations")

_VERSION = re.compile(r"^(\d+)\.(\d+)$")


def parse_target(version: str) -> tuple[int, int]:
    """'4.2' -> (4, 2). The editor's export `version` takes major.minor only
    ("4.2.43" is refused: "Invalid JSON version")."""
    m = _VERSION.match(str(version).strip())
    if not m:
        raise ValueError(
            f"target_version must be major.minor (e.g. \"4.2\"), got {version!r}: "
            "the Spine export setting refuses a patch number"
        )
    return int(m.group(1)), int(m.group(2))


def _identity_mapping(name: str, entry: dict) -> bool:
    """A 4.3 `properties` entry that 4.2 can express: from P to P only, no
    offset, no scale, no max."""
    if entry.get("offset", 0) not in (0, 0.0):
        return False
    to = entry.get("to") or {}
    if set(to) != {name}:
        return False
    t = to[name] or {}
    return t.get("offset", 0) in (0, 0.0) and t.get("scale", 1) in (1, 1.0) and "max" not in t


def losses(data: dict, target_version: str = "4.2") -> list[dict[str, Any]]:
    """List the 4.3-only features of `data` that an export to
    `target_version` drops. Each item: {feature, name, detail}. Empty when the
    target is 4.3 or newer."""
    if parse_target(target_version) >= (4, 3):
        return []
    out: list[dict[str, Any]] = []

    def add(feature: str, name: str, detail: str) -> None:
        out.append({"feature": feature, "name": name, "detail": detail})

    for c in data.get("constraints") or []:
        kind, name = c.get("type"), c.get("name", "?")
        if kind == "slider":
            add("slider", name, f"slider driving animation {c.get('animation')!r}: dropped, its pose reverts to setup")
        elif kind in ("ik", "physics") and c.get("scaleY") == "volume":
            add(f"{kind}_volume", name, f"{kind} scaleY mode 'volume' has no older equivalent")
        elif kind == "transform":
            props = c.get("properties") or {}
            odd = [p for p, e in props.items() if not _identity_mapping(p, e or {})]
            if odd:
                add("transform_mapping", name,
                    "property mapping (other target property, scale, offset or max) on: " + ", ".join(odd))

    for skin in data.get("skins") or []:
        for slot, atts in (skin.get("attachments") or {}).items():
            for att_name, a in (atts or {}).items():
                t = a.get("type", "region")
                if t == "clipping" and a.get("inverse"):
                    add("inverse_clipping", f"{skin.get('name')}/{slot}/{att_name}", "inverse clipping is ignored")
                if t == "linkedmesh" and a.get("slot") not in (None, slot):
                    add("linked_mesh_other_slot", f"{skin.get('name')}/{slot}/{att_name}",
                        f"source mesh {a.get('source', a.get('parent'))!r} is in slot {a.get('slot')!r}")

    for anim_name, anim in (data.get("animations") or {}).items():
        sl = anim.get("slider") or {}
        if sl:
            add("slider_keys", anim_name, "slider timelines on: " + ", ".join(sorted(sl)))
        if anim.get("drawOrderFolder"):
            add("draw_order_folder_keys", anim_name, "drawOrderFolder timelines are dropped")
    return out


def foreign_keys(data: dict) -> list[str]:
    """Top-level keys of an exported JSON that the 4.2 reader ignores (an
    export to 4.2 writes a slider into `slider`)."""
    return [k for k in data if k not in KEYS_42]


def summary(items: list[dict[str, Any]], target_version: str) -> list[str]:
    """One warning per feature kind (names grouped)."""
    by: dict[str, list[str]] = {}
    for it in items:
        by.setdefault(it["feature"], []).append(it["name"])
    return [
        f"export to {target_version} drops {kind} ({len(names)}): {', '.join(names[:8])}"
        + (" ..." if len(names) > 8 else "")
        for kind, names in by.items()
    ]
