"""End-to-end PSD -> Spine 4.3 project conversion.

Pure function (no MCP/IO framework coupling) so it's directly testable. The MCP
tool in `server.py` is a thin wrapper over this.

Outputs, in `out_dir`:
- `<name>.json`  Spine 4.3 skeleton (import it with Spine > Import Data, or
  `spine_import_data` to build a `.spine` project)
- `<name>.atlas` + `<name>.png` page(s), for runtimes (Unity, Godot, web...)
- `images/<part>.png` (optional) individual images referenced by
  `skeleton.images`, so the editor shows the art right after import
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .atlas.writer import compose_pages, write_atlas_text
from .psd.parser import parse_psd
from .spine import document as doc
from .spine import generators as gen
from .spine.builder import build
from .spine.constraints import ik_for_chain
from .spine.writer import to_dict


@dataclass
class ImportResult:
    project_path: Path
    atlas_path: Path
    png_paths: list[Path]
    image_paths: list[Path] = field(default_factory=list)
    animations: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


def import_psd_to_spine(
    psd_path: str,
    out_dir: str,
    name: str | None = None,
    orient_bones: bool = False,
    export_images: bool = False,
    ik_legs: bool = False,
    ik_arms: bool = False,
    animations: Sequence[str] = (),
) -> ImportResult:
    psd_path = str(psd_path)
    stem = name or Path(psd_path).stem
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    parsed = parse_psd(psd_path)
    result = build(parsed, orient_bones=orient_bones or ik_legs or ik_arms)
    data = to_dict(result.project)

    image_paths: list[Path] = []
    if export_images:
        img_dir = out / "images"
        img_dir.mkdir(exist_ok=True)
        for part, layer in result.images.items():
            p = img_dir / f"{part}.png"
            layer.image.convert("RGBA").save(p)
            image_paths.append(p)
        data["skeleton"]["images"] = "./images/"

    added: list[str] = []
    chains = []
    if ik_legs:
        chains += [("leg_left", "foot_left"), ("leg_right", "foot_right")]
    if ik_arms:
        chains += [("arm_left", "hand_left"), ("arm_right", "hand_right")]
    for upper, lower in chains:
        if doc.has_bone(data, upper) and doc.has_bone(data, lower):
            res = ik_for_chain(data, [upper, lower], bend_positive=upper.startswith("leg"))
            added.append(res["constraint"]["name"])

    for preset in animations:
        fn = gen.PRESETS.get(preset)
        if fn is None:
            raise ValueError(f"unknown animation preset {preset!r}; use {sorted(gen.PRESETS)}")
        before = set(doc.animations(data))
        try:
            fn(data)
        except gen.AnimationError:
            # Rig lacks the bones for this preset: drop what it started.
            for n in set(doc.animations(data)) - before:
                del doc.animations(data)[n]

    project_path = out / f"{stem}.json"
    doc.save(data, project_path)
    atlas_path = write_atlas_text(result.atlas, stem, out / f"{stem}.atlas")
    images = {n: layer.image for n, layer in result.images.items()}
    png_paths = compose_pages(result.atlas, images, stem, out)

    return ImportResult(
        project_path=project_path,
        atlas_path=atlas_path,
        png_paths=png_paths,
        image_paths=image_paths,
        animations=sorted(doc.animations(data)),
        constraints=added,
    )
