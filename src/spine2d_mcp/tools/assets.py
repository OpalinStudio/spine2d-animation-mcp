"""MCP tools: PSD import and texture atlases (pure Python, no Spine needed)."""

from __future__ import annotations

from pathlib import Path

from .. import pipeline
from ..atlas import reader, writer
from ._common import mcp, resolve


@mcp.tool()
def import_psd_to_spine(
    psd_path: str,
    out_dir: str | None = None,
    name: str | None = None,
    orient_bones: bool = True,
    export_images: bool = True,
    ik_legs: bool = False,
    ik_arms: bool = False,
    animations: list[str] | None = None,
) -> dict:
    """Convert a layered PSD character into a Spine 4.3 rig: skeleton JSON,
    texture atlas + PNG page(s) and (export_images) one PNG per part in
    images/ so the Spine editor shows the art right after import.

    Layers named after body parts become bones + slots + region attachments:
    head, neck, body/torso, chest, hip/pelvis, arm_left/right,
    hand_left/right, leg_left/right, foot_left/right (missing spine bones are
    created). A `<part>[pivot]` layer sets a custom pivot. PSD order = draw
    order.

    Args:
        psd_path: Absolute path to the .psd.
        out_dir: Output folder (default "<psd folder>/<psd name>_spine").
        name: Base name of the outputs (default: PSD file name).
        orient_bones: Bones point along their part with a length (needed for IK).
        ik_legs / ik_arms: Add IK targets + constraints for legs / arms.
        animations: Presets to generate right away: idle, walk, run, jump,
            wave, nod, blink (presets missing bones are skipped).

    Next: spine_import_data(json, project.spine) to get a .spine project.
    """
    src = Path(psd_path)
    if out_dir is None:
        out_dir = str(src.parent / f"{src.stem}_spine")
    result = pipeline.import_psd_to_spine(
        psd_path, out_dir, name=name, orient_bones=orient_bones, export_images=export_images,
        ik_legs=ik_legs, ik_arms=ik_arms, animations=animations or (),
    )
    return {
        "project_path": str(result.project_path),
        "atlas_path": str(result.atlas_path),
        "png_paths": [str(p) for p in result.png_paths],
        "image_paths": [str(p) for p in result.image_paths],
        "animations": result.animations,
        "constraints": result.constraints,
    }


@mcp.tool()
def pack_atlas(
    images_dir: str,
    out_dir: str,
    name: str,
    max_size: int = 2048,
    padding: int = 2,
) -> dict:
    """Pack a folder of PNGs into a Spine/libgdx texture atlas WITHOUT Spine
    (rectangles, no rotation, power-of-two pages). Region names = relative
    paths without extension. For polygon packing, whitespace stripping,
    premultiplied alpha, per-skin atlases or scales use spine_pack (Spine
    texture packer)."""
    atlas_path, pages, names = writer.pack_folder(images_dir, out_dir, name, max_size, padding)
    return {"atlas": str(atlas_path), "pages": [str(p) for p in pages], "regions": len(names)}


@mcp.tool()
def read_atlas(atlas: str) -> dict:
    """List the pages and regions (bounds, rotation, offsets) of a .atlas."""
    return reader.read_atlas(resolve(atlas)).as_dict()


@mcp.tool()
def unpack_atlas_images(atlas: str, out_dir: str) -> dict:
    """Extract every region of a .atlas to individual PNGs (restoring
    stripped whitespace and rotation) WITHOUT Spine. Use spine_unpack with a
    project to also restore polygon-packed meshes."""
    files = reader.unpack_atlas(resolve(atlas), resolve(out_dir))
    return {"out_dir": str(resolve(out_dir)), "images": len(files)}
