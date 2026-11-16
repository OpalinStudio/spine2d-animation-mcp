"""render_preview must not report image-less attachments (clipping, point,
boundingbox, path) as missing images: they have no texture to look up."""
from pathlib import Path

from PIL import Image

from spine2d_mcp.tools import animation, skeleton as sk


def test_imageless_attachments_are_not_missing_images(tmp_path: Path):
    j = str(tmp_path / "probe.json")
    sk.create_skeleton(j, overwrite=True)
    (tmp_path / "images").mkdir()
    Image.new("RGBA", (40, 40), (200, 60, 60, 255)).save(tmp_path / "images" / "carre.png")
    for s in ["carre", "clip", "pt", "bb", "chemin"]:
        sk.add_slot(j, s, "root")
    sk.add_region_attachment(j, "carre", "carre", 40, 40)
    sk.add_clipping_attachment(j, "clip", "masque", [[-30, -30], [30, -30], [30, 30], [-30, 30]], end_slot="carre")
    sk.add_point_attachment(j, "pt", "spawn", 5, 5)
    sk.add_bounding_box(j, "bb", "hit", [[-20, -20], [20, -20], [20, 20], [-20, 20]])
    sk.add_path_attachment(j, "chemin", "trace", [[-30, 0], [0, 30], [30, 0]])
    res = animation.render_preview(j, str(tmp_path / "out.png"), width=200, height=200)
    assert res["missing_images"] == []
    img = Image.open(tmp_path / "out.png").convert("RGB")
    # the region is still drawn
    assert img.getpixel((100, 100)) == (200, 60, 60)


def test_real_missing_region_still_reported(tmp_path: Path):
    j = str(tmp_path / "probe.json")
    sk.create_skeleton(j, overwrite=True)
    (tmp_path / "images").mkdir()
    sk.add_slot(j, "s", "root")
    sk.add_slot(j, "pt", "root")
    sk.add_region_attachment(j, "s", "absent", 40, 40)
    sk.add_point_attachment(j, "pt", "spawn", 5, 5)
    res = animation.render_preview(j, str(tmp_path / "out.png"), width=200, height=200)
    assert res["missing_images"] == ["absent"]
