"""Atlas files whose region fields are NOT indented (as written by some
exporters / packers): the official runtime reads any line containing ':' as a
field (TextureAtlas.ts readEntry), so the reader must too."""

from PIL import Image

from spine2d_mcp.atlas.reader import read_atlas, unpack_atlas

INDENTED = """\
sheet.png
\tsize: 64,32
\tfilter: Linear,Linear
\tpma: false
red
\tbounds: 0,0,16,8
\toffsets: 1,2,20,12
green
\tbounds: 20,0,8,16
\trotate: 90
"""

UNINDENTED = """\
sheet.png
size:64,32
filter:Linear,Linear
pma:false
red
bounds:0,0,16,8
offsets:1,2,20,12
green
bounds:20,0,8,16
rotate:90
"""


def _page(tmp_path):
    img = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (0, 0, 16, 8))
    img.paste((0, 255, 0, 255), (20, 0, 36, 8))  # 8x16 rotated 90 -> 16x8 packed
    img.save(tmp_path / "sheet.png")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_unindented_fields_parse_like_indented(tmp_path):
    _page(tmp_path)
    a = read_atlas(_write(tmp_path, "a.atlas", INDENTED)).as_dict()
    b = read_atlas(_write(tmp_path, "b.atlas", UNINDENTED)).as_dict()
    assert [r["name"] for r in b["regions"]] == ["red", "green"]
    assert b == a
    red, green = b["regions"]
    assert red["bounds"] == [0, 0, 16, 8] and red["orig"] == [20, 12] and red["offset"] == [1, 2]
    assert green["bounds"] == [20, 0, 8, 16] and green["rotate"] == 90
    assert b["pages"][0]["size"] == [64, 32]


def test_unindented_two_pages(tmp_path):
    text = UNINDENTED + "\nother.png\nsize:8,8\nblue\nbounds:0,0,4,4\n"
    atlas = read_atlas(_write(tmp_path, "c.atlas", text))
    assert [p.name for p in atlas.pages] == ["sheet.png", "other.png"]
    assert [(r.name, r.page, r.width) for r in atlas.regions] == [
        ("red", "sheet.png", 16), ("green", "sheet.png", 8), ("blue", "other.png", 4)]


def test_unindented_unpack_writes_real_images(tmp_path):
    _page(tmp_path)
    out = unpack_atlas(_write(tmp_path, "b.atlas", UNINDENTED), tmp_path / "out")
    assert sorted(p.name for p in out) == ["green.png", "red.png"]
    red = Image.open(tmp_path / "out" / "red.png")
    assert red.size == (20, 12)
    assert red.getpixel((1, 12 - 2 - 1)) == (255, 0, 0, 255)
    assert Image.open(tmp_path / "out" / "green.png").size == (8, 16)
