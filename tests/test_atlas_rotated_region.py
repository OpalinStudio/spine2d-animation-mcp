"""Regions packed with `rotate: 90` must come back upright.

Spine's texture packer stores such a region turned 90 degrees counter-clockwise
in the page (the runtime then swaps UVs). Checked against the real Spine 4.3.26
packer: a 200x30 image packed with rotation came back from `region_image`
turned 180 degrees (mean difference 109/255) before the fix, 0 after.
"""

from PIL import Image, ImageChops

from spine2d_mcp.atlas.reader import read_atlas, region_image, unpack_atlas


def _asym(w: int, h: int) -> Image.Image:
    """Image with no rotational or mirror symmetry (gradients + corner mark)."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    for y in range(h):
        for x in range(w):
            im.putpixel((x, y), ((x * 255) // w, (y * 255) // h, 40, 255))
    im.paste((255, 255, 255, 255), (0, 0, 3, 2))  # top-left marker
    return im


def _atlas(tmp_path, degrees_line: str, packed: Image.Image, w: int, h: int, extra: str = ""):
    page = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    page.paste(packed, (4, 6))
    page.save(tmp_path / "sheet.png")
    text = (
        "sheet.png\n\tsize: 64, 64\n\tfilter: Linear, Linear\n"
        f"r\n\tbounds: 4, 6, {w}, {h}\n{extra}{degrees_line}"
    )
    p = tmp_path / "r.atlas"
    p.write_text(text, encoding="utf-8")
    return p


def _same(a: Image.Image, b: Image.Image) -> bool:
    # getbbox() on RGBA looks at alpha only: compare every channel
    return a.size == b.size and ImageChops.difference(a, b).getbbox(alpha_only=False) is None


def test_rotate_90_region_comes_back_upright(tmp_path):
    orig = _asym(20, 6)
    packed = orig.transpose(Image.Transpose.ROTATE_90)  # how Spine packs it (6x20 in the page)
    p = _atlas(tmp_path, "\trotate: 90\n", packed, 20, 6)
    atlas = read_atlas(p)
    got = region_image(atlas, atlas.regions[0])
    assert _same(got, orig)


def test_rotate_true_is_the_same_as_90(tmp_path):
    orig = _asym(20, 6)
    p = _atlas(tmp_path, "\trotate: true\n", orig.transpose(Image.Transpose.ROTATE_90), 20, 6)
    out = unpack_atlas(p, tmp_path / "out")
    assert _same(Image.open(out[0]).convert("RGBA"), orig)


def test_rotate_270_region_comes_back_upright(tmp_path):
    orig = _asym(20, 6)
    p = _atlas(tmp_path, "\trotate: 270\n", orig.transpose(Image.Transpose.ROTATE_270), 20, 6)
    atlas = read_atlas(p)
    assert _same(region_image(atlas, atlas.regions[0]), orig)


def test_rotate_90_with_stripped_whitespace(tmp_path):
    orig = _asym(20, 6)
    p = _atlas(tmp_path, "\trotate: 90\n", orig.transpose(Image.Transpose.ROTATE_90), 20, 6,
               extra="\toffsets: 2, 3, 24, 12\n")
    atlas = read_atlas(p)
    got = region_image(atlas, atlas.regions[0])
    assert got.size == (24, 12)
    # offsets are from the bottom-left: x=2, top = 12 - 3 - 6 = 3
    assert _same(got.crop((2, 3, 22, 9)), orig)
    assert got.getpixel((0, 0)) == (0, 0, 0, 0)
