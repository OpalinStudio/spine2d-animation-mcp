"""Write the libgdx `.atlas` text file and compose atlas PNG page(s).

Format verified against `reference/spineboy.atlas` (spine-runtimes 4.2):

    page.png
    \tsize: W, H
    \tfilter: Linear, Linear
    region-name
    \tbounds: x, y, w, h

Header uses tab indentation; region lines have no indent, their attribute lines
are tab-indented. `bounds:` packs x,y,w,h (4.2 short form). No `rotate:` since
the packer disables rotation. Atlas y-origin is top-left, matching the PNG.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .packer import AtlasLayout, PlacedRegion


def _page_name(stem: str, page_idx: int, total_pages: int) -> str:
    if total_pages == 1:
        return f"{stem}.png"
    return f"{stem}_{page_idx + 1}.png"


def write_atlas_text(
    layout: AtlasLayout,
    stem: str,
    path: str | Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(layout.pages)
    by_page: dict[int, list[PlacedRegion]] = {}
    for r in layout.regions:
        by_page.setdefault(r.page, []).append(r)

    lines: list[str] = []
    for page_idx in range(total):
        w, h = layout.pages[page_idx]
        if page_idx > 0:
            lines.append("")
        lines.append(_page_name(stem, page_idx, total))
        lines.append(f"\tsize: {w}, {h}")
        lines.append("\tfilter: Linear, Linear")
        for r in sorted(by_page.get(page_idx, []), key=lambda x: x.name):
            lines.append(r.name)
            lines.append(f"\tbounds: {r.x}, {r.y}, {r.width}, {r.height}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def compose_pages(
    layout: AtlasLayout,
    images: dict[str, Image.Image],
    stem: str,
    out_dir: str | Path,
) -> list[Path]:
    """Blit each region's PNG onto its atlas page and save the page PNG(s)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(layout.pages)
    pages = [
        Image.new("RGBA", layout.pages[i], (0, 0, 0, 0)) for i in range(total)
    ]
    for r in layout.regions:
        img = images[r.name].convert("RGBA")
        pages[r.page].paste(img, (r.x, r.y))

    paths: list[Path] = []
    for i, page in enumerate(pages):
        p = out_dir / _page_name(stem, i, total)
        page.save(p, "PNG")
        paths.append(p)
    return paths


def pack_folder(
    images_dir: str | Path,
    out_dir: str | Path,
    name: str,
    max_size: int = 2048,
    padding: int = 2,
) -> tuple[Path, list[Path], list[str]]:
    """Pack every PNG of a folder (recursively) into `<name>.atlas` + pages.
    Region names are the paths relative to the folder without extension
    (`arm/left.png` -> `arm/left`), as the Spine texture packer names them."""
    from .packer import Region, pack

    images_dir = Path(images_dir)
    files = sorted(p for p in images_dir.rglob("*.png") if p.is_file())
    if not files:
        raise ValueError(f"no PNG images in {images_dir}")
    images: dict[str, Image.Image] = {}
    regions = []
    for p in files:
        rel = p.relative_to(images_dir).with_suffix("").as_posix()
        img = Image.open(p).convert("RGBA")
        images[rel] = img
        regions.append(Region(name=rel, width=img.width, height=img.height))
    layout = pack(regions, max_size=max_size, padding=padding)
    out_dir = Path(out_dir)
    atlas_path = write_atlas_text(layout, name, out_dir / f"{name}.atlas")
    pages = compose_pages(layout, images, name, out_dir)
    return atlas_path, pages, list(images)
