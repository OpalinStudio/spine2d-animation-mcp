"""Parse a PSD into a flat list of pixel layers plus its bone groups.

Only visible pixel layers with a bbox are returned. Coordinates are PSD-native
(origin top-left, y-down); the builder converts to Spine y-up.

Layer order CONTRACT: `ParsedPsd.layers` is bottom-to-top in PSD z-order
(psd-tools iterates a node bottom-up). The builder relies on this for Spine
slot draw order, so this ordering must be preserved.

Groups: a group named after a body part (`head`, `arm_left`...) or tagged
`[bone]` is a *bone group*: the layers inside it hang off that bone. Other
groups are just folders. A layer or group tagged `[ignore]` is skipped.

Pivot-override marker layers (`<name>[pivot]`) are split out into
`pivot_markers` and not treated as images.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image
from psd_tools import PSDImage

from .conventions import (
    BONE_TAG,
    IGNORE_TAG,
    canonical_part,
    pivot_marker_key,
    strip_tags,
)


@dataclass
class PsdLayer:
    name: str
    # bbox in PSD coordinates: top-left origin, y-down.
    left: int
    top: int
    width: int
    height: int
    image: Image.Image | None
    # Name of the enclosing bone group (see PsdGroup), if any.
    group: str | None = None

    @property
    def center(self) -> tuple[float, float]:
        return self.left + self.width / 2.0, self.top + self.height / 2.0


@dataclass
class PsdGroup:
    """A group that maps to a bone: a body part, or a `[bone]` group."""

    name: str  # canonical part, or the group's own name for a `[bone]` group
    parent: str | None  # enclosing bone group
    canonical: bool
    # Union bbox of the layers inside (PSD coords), None while empty.
    box: tuple[int, int, int, int] | None = None

    def as_layer(self) -> PsdLayer | None:
        if self.box is None:
            return None
        left, top, right, bottom = self.box
        return PsdLayer(self.name, left, top, right - left, bottom - top, None, self.parent)


@dataclass
class ParsedPsd:
    width: int
    height: int
    layers: list[PsdLayer]  # bottom-to-top z-order
    # canonical part (or normalized layer / group name) -> PSD-space center of
    # its pivot marker
    pivot_markers: dict[str, tuple[float, float]] = field(default_factory=dict)
    # bone groups, parents before children
    groups: dict[str, PsdGroup] = field(default_factory=dict)


def parse_psd(file_path: str) -> ParsedPsd:
    psd = PSDImage.open(file_path)
    parsed = ParsedPsd(width=psd.width, height=psd.height, layers=[])
    _collect(psd, parsed, None)
    return parsed


def _bone_group(layer, parsed: ParsedPsd, parent: str | None) -> str | None:
    """Register the group as a bone group and return its name (None for a
    plain folder)."""
    name = strip_tags(layer.name)
    part = canonical_part(name)
    if part is None and BONE_TAG not in layer.name.lower():
        return None
    key = part or name
    if key not in parsed.groups:
        parsed.groups[key] = PsdGroup(key, parent if parent != key else None, part is not None)
    return key


def _grow(parsed: ParsedPsd, group: str | None, box: tuple[int, int, int, int]) -> None:
    seen: set[str] = set()
    while group is not None and group not in seen:
        seen.add(group)
        g = parsed.groups[group]
        g.box = box if g.box is None else (
            min(g.box[0], box[0]), min(g.box[1], box[1]), max(g.box[2], box[2]), max(g.box[3], box[3]))
        group = g.parent


def _collect(node, parsed: ParsedPsd, group: str | None) -> None:
    for layer in node:
        if not layer.is_visible() or IGNORE_TAG in layer.name.lower():
            continue
        if layer.is_group():
            _collect(layer, parsed, _bone_group(layer, parsed, group) or group)
            continue
        if not layer.has_pixels():
            continue
        image = layer.composite()
        if image is None:
            continue
        left, top, right, bottom = layer.bbox

        marker = pivot_marker_key(layer.name)
        if marker is not None:
            cx = left + (right - left) / 2.0
            cy = top + (bottom - top) / 2.0
            parsed.pivot_markers[marker] = (cx, cy)
            continue

        _grow(parsed, group, (left, top, right, bottom))
        parsed.layers.append(
            PsdLayer(
                name=layer.name,
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                image=image,
                group=group,
            )
        )


__all__ = ["ParsedPsd", "PsdGroup", "PsdLayer", "parse_psd"]
