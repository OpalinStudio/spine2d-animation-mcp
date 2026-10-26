"""Read libgdx/Spine `.atlas` files (4.x short form and the legacy long form)
and cut regions back out of the page images.

Region fields handled: bounds (x, y, w, h), offsets (x, y, origW, origH),
rotate (true / false / 90 / degrees), index, plus the legacy xy/size/orig/
offset lines. Page fields: size, format, filter, repeat, pma, scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


@dataclass
class AtlasRegion:
    name: str
    page: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    offset_x: int = 0
    offset_y: int = 0
    orig_width: int = 0
    orig_height: int = 0
    degrees: int = 0
    index: int = -1
    extra: dict = field(default_factory=dict)


@dataclass
class AtlasPage:
    name: str
    width: int = 0
    height: int = 0
    pma: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class Atlas:
    path: Path
    pages: list[AtlasPage]
    regions: list[AtlasRegion]

    def find(self, name: str, index: int = -1) -> AtlasRegion | None:
        for r in self.regions:
            if r.name == name and (index == -1 or r.index == index):
                return r
        return None

    def as_dict(self) -> dict:
        return {
            "pages": [
                {"name": p.name, "size": [p.width, p.height], "pma": p.pma, **p.extra}
                for p in self.pages
            ],
            "regions": [
                {
                    "name": r.name,
                    "page": r.page,
                    "bounds": [r.x, r.y, r.width, r.height],
                    "orig": [r.orig_width, r.orig_height],
                    "offset": [r.offset_x, r.offset_y],
                    "rotate": r.degrees,
                    **({"index": r.index} if r.index != -1 else {}),
                }
                for r in self.regions
            ],
        }


def _ints(v: str) -> list[int]:
    return [int(float(x)) for x in v.split(",")]


def read_atlas(path: str | Path) -> Atlas:
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    pages: list[AtlasPage] = []
    regions: list[AtlasRegion] = []
    page: AtlasPage | None = None
    region: AtlasRegion | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            page = None
            region = None
            continue
        if ":" in line and (raw[:1] in (" ", "\t") or region is None and page is not None and not _is_name(line)):
            key, _, value = line.strip().partition(":")
            key, value = key.strip(), value.strip()
            target = region if region is not None else page
            if target is None:
                continue
            _set_field(target, key, value)
            continue
        if page is None:
            page = AtlasPage(name=line.strip())
            pages.append(page)
            region = None
        else:
            region = AtlasRegion(name=line.strip(), page=page.name)
            regions.append(region)
    for r in regions:
        if not r.orig_width:
            r.orig_width, r.orig_height = r.width, r.height
    return Atlas(path=path, pages=pages, regions=regions)


def _is_name(line: str) -> bool:
    key = line.split(":", 1)[0].strip()
    return key not in {
        "size", "format", "filter", "repeat", "pma", "scale", "bounds", "offsets",
        "rotate", "index", "xy", "orig", "offset", "split", "pad",
    }


def _set_field(target, key: str, value: str) -> None:
    if isinstance(target, AtlasPage):
        if key == "size":
            target.width, target.height = _ints(value)[:2]
        elif key == "pma":
            target.pma = value.lower() == "true"
        else:
            target.extra[key] = value
        return
    r: AtlasRegion = target
    if key == "bounds":
        r.x, r.y, r.width, r.height = _ints(value)
    elif key == "offsets":
        r.offset_x, r.offset_y, r.orig_width, r.orig_height = _ints(value)
    elif key == "xy":
        r.x, r.y = _ints(value)
    elif key == "size":
        r.width, r.height = _ints(value)
    elif key == "orig":
        r.orig_width, r.orig_height = _ints(value)
    elif key == "offset":
        r.offset_x, r.offset_y = _ints(value)
    elif key == "rotate":
        v = value.lower()
        r.degrees = 90 if v == "true" else 0 if v == "false" else int(float(v))
    elif key == "index":
        r.index = int(value)
    else:
        r.extra[key] = value


def region_image(atlas: Atlas, region: AtlasRegion, cache: dict | None = None) -> Image.Image:
    """Region as an un-rotated RGBA image at its ORIGINAL size (whitespace
    stripped by the packer is restored as transparency)."""
    cache = cache if cache is not None else {}
    page_path = atlas.path.parent / region.page
    page = cache.get(page_path)
    if page is None:
        page = Image.open(page_path).convert("RGBA")
        cache[page_path] = page
    w, h = region.width, region.height
    packed_w, packed_h = (h, w) if region.degrees in (90, 270) else (w, h)
    img = page.crop((region.x, region.y, region.x + packed_w, region.y + packed_h))
    if region.degrees == 90:
        img = img.transpose(Image.Transpose.ROTATE_90)
    elif region.degrees == 270:
        img = img.transpose(Image.Transpose.ROTATE_270)
    elif region.degrees:
        img = img.rotate(region.degrees, expand=True)
    if (region.orig_width, region.orig_height) != (w, h) or region.offset_x or region.offset_y:
        full = Image.new("RGBA", (region.orig_width, region.orig_height), (0, 0, 0, 0))
        # offsets are from the bottom-left of the original image
        full.paste(img, (region.offset_x, region.orig_height - region.offset_y - h))
        img = full
    return img


def unpack_atlas(atlas_path: str | Path, out_dir: str | Path) -> list[Path]:
    """Write every region of an atlas as an individual PNG (pure Python
    alternative to `Spine --unpack`, without polygon restoration)."""
    atlas = read_atlas(atlas_path)
    out = Path(out_dir)
    cache: dict = {}
    written = []
    for r in atlas.regions:
        name = r.name if r.index == -1 else f"{r.name}_{r.index}"
        p = out / f"{name}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        region_image(atlas, r, cache).save(p)
        written.append(p)
    return written
