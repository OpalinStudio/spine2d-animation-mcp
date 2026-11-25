"""Art quality control: each check fires on the defect it names, stays quiet
on a clean part, and the repairs fix what they claim without changing the
drawing's size."""

import asyncio
import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from spine2d_mcp.atlas import writer
from spine2d_mcp.spine import analysis, art
from spine2d_mcp.spine import attachments as att
from spine2d_mcp.spine import document as doc
from spine2d_mcp.tools import mcp, quality

DARK = (40, 50, 90, 255)


def _disc(size=160, color=DARK, antialiased=True, radius=None):
    """A filled disc, with a soft (antialiased) or a hard (thresholded) edge."""
    k = 4 if antialiased else 1
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    r = (radius or size * 0.4) * k
    c = size * k / 2
    ImageDraw.Draw(img).ellipse([c - r, c - r, c + r, c + r], fill=color)
    return img.resize((size, size), Image.Resampling.LANCZOS) if antialiased else img


def _codes(report, severity="warning"):
    return {i["code"] for i in report["issues"] if i["severity"] == severity}


def test_clean_antialiased_part_has_no_finding():
    rep = art.check_image(_disc(), "disc")
    assert rep["issues"] == []
    assert rep["metrics"]["hard_edge"] < 0.1 and rep["metrics"]["pieces"] == 1


def test_hard_edges_are_found_and_softened_in_place():
    hard = _disc(antialiased=False)
    rep = art.check_image(hard, "disc")
    assert _codes(rep) == {"hard_edges"} and rep["metrics"]["hard_edge"] == 1.0
    fixed, done = art.clean_image(hard)
    assert done["softened_px"] == 0.8 and fixed.size == hard.size
    assert _codes(art.check_image(fixed, "disc")) == set()
    # Inwards only: nothing appears outside the original shape, the inside stays opaque.
    before, after = np.asarray(hard)[..., 3], np.asarray(fixed)[..., 3]
    assert (after <= before).all() and after[80, 80] == 255
    # A part that is already antialiased is left alone.
    assert "softened_px" not in art.clean_image(_disc())[1]


def test_fragments_are_found_boxed_and_removed():
    img = _disc()
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, 9, 8], fill=DARK)
    d.rectangle([150, 140, 153, 146], fill=DARK)
    rep = art.check_image(img, "part")
    assert _codes(rep) == {"fragments"} and rep["metrics"]["fragments"] == 2
    assert "2 detached fragment(s), 58 px" in rep["issues"][0]["message"]
    assert [4, 4, 10, 9] in rep["marks"]["fragments"] or [2, 2, 8, 7] in rep["marks"]["fragments"]
    fixed, done = art.clean_image(img)
    assert done["fragments_removed"] == {"count": 2, "px": 58}
    alpha = np.asarray(fixed)[..., 3]
    assert alpha[6, 6] == 0 and alpha[143, 151] == 0 and alpha[80, 80] == 255
    assert art.check_image(fixed, "part")["issues"] == []


def test_two_comparable_pieces_are_reported_not_removed():
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    img.alpha_composite(_disc(90), (5, 5))
    img.alpha_composite(_disc(90), (105, 5))
    rep = art.check_image(img, "eyes")
    assert _codes(rep) == set() and _codes(rep, "info") == {"several_pieces"}
    assert "fragments_removed" not in art.clean_image(img)[1]


def test_frayed_and_torn_outlines():
    def star(points, inner):
        img = Image.new("RGBA", (880, 880), (0, 0, 0, 0))
        pts = [(440 + (400 if i % 2 == 0 else inner) * math.cos(math.pi * i / points),
                440 + (400 if i % 2 == 0 else inner) * math.sin(math.pi * i / points))
               for i in range(2 * points)]
        ImageDraw.Draw(img).polygon(pts, fill=DARK)
        return img.resize((220, 220), Image.Resampling.LANCZOS)

    fray = art.check_image(star(60, 370), "fray")  # a fringe of thin spikes all around
    assert "frayed_edges" in _codes(fray) and "fray left by the cut-out" in fray["issues"][0]["message"]
    torn = art.check_image(star(7, 150), "torn")  # a few large spikes
    assert "frayed_edges" in _codes(torn) and "torn cut-out" in torn["issues"][0]["message"]
    assert torn["metrics"]["shape_roughness"] > torn["metrics"]["edge_roughness"]
    assert "rough" in torn["marks"] and "worst around x=" in torn["issues"][0]["where"]
    # Trimming shortens the fray without changing the size of the image.
    fixed, done = art.clean_image(star(60, 370), smooth=3)
    after = art.check_image(fixed, "fray")
    assert done["smoothed_px"] == 3 and fixed.size == (220, 220)
    assert after["metrics"]["edge_roughness"] < 0.7 * fray["metrics"]["edge_roughness"]


def test_light_fringe_of_a_removed_background():
    img = _disc(color=(245, 245, 245, 255))
    img.alpha_composite(_disc(radius=61))
    assert _codes(art.check_image(img, "part")) == {"light_fringe"}
    # A dark outline around a lighter fill is the normal cartoon case: no finding.
    outlined = _disc(color=(10, 10, 10, 255))
    outlined.alpha_composite(_disc(color=(240, 150, 30, 255), radius=60))
    assert art.check_image(outlined, "part")["issues"] == []


def test_translucent_and_empty_images_are_not_cut_out_defects():
    shadow = _disc(color=(0, 0, 0, 90))
    assert art.check_image(shadow, "shadow") == {
        "name": "shadow", "metrics": {"size": [160, 160], "area_px": 0, "translucent": True},
        "issues": [], "marks": {}}
    empty = art.check_image(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), "vide")
    assert _codes(empty) == set() and _codes(empty, "info") == {"empty"}
    smoke = _disc()
    smoke.putalpha(smoke.getchannel("A").point(lambda v: v // 2 if v else 0))
    half = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    half.alpha_composite(_disc())
    half.paste(smoke.crop((60, 60, 100, 100)), (60, 60))
    assert _codes(art.check_image(half, "part"), "info") == {"see_through"}


def test_part_softer_than_the_rest_of_the_set():
    def lined(blur):
        img = _disc(200)
        d = ImageDraw.Draw(img)
        for x in range(70, 140, 12):
            d.line([x, 60, x, 140], fill=(240, 240, 240, 255), width=2)
        if blur:
            small = img.resize((50, 50), Image.Resampling.BILINEAR)
            img = small.resize((200, 200), Image.Resampling.BICUBIC)
        return img

    reports = art.check_images({"a": lined(False), "b": lined(False), "c": lined(False), "blurry": lined(True)})
    soft = [r["name"] for r in reports if "soft_art" in _codes(r, "info")]
    assert soft == ["blurry"]


def test_bleed_spreads_colour_under_the_rim_without_touching_alpha():
    img = _disc(antialiased=False)
    arr = np.asarray(img)
    assert tuple(arr[80, 10]) == (0, 0, 0, 0)  # transparent black next to the art
    out = art.bleed_colors(arr, 4)
    assert (out[..., 3] == arr[..., 3]).all()
    edge = int(np.argmax(arr[80, :, 3] > 0))
    assert tuple(out[80, edge - 1, :3]) == DARK[:3] and tuple(out[80, edge - 4, :3]) == DARK[:3]
    assert tuple(out[80, edge - 6]) == (0, 0, 0, 0)  # only as far as asked


def test_packed_atlas_pages_carry_the_bleed(tmp_path):
    (tmp_path / "images").mkdir()
    _disc(antialiased=False).save(tmp_path / "images" / "disc.png")
    _, pages, _ = writer.pack_folder(tmp_path / "images", tmp_path / "out", "skin")
    page = np.asarray(Image.open(pages[0]).convert("RGBA"))
    ys, xs = np.nonzero(page[..., 3])
    y, x = int(ys.min()), int(xs[ys == ys.min()][0])
    assert tuple(page[y - 1, x]) == (*DARK[:3], 0) and tuple(page[y - 2, x]) == (*DARK[:3], 0)


# ------------------------------------------------------------- skeleton
def _limb(tmp_path, lower_image):
    """root > upper > lower, two 100 x 40 sleeves meeting at x = 100."""
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    Image.new("RGBA", (100, 40), DARK).save(images / "upper.png")
    lower_image.save(images / "lower.png")
    sk = tmp_path / "limb.json"
    data = doc.new_skeleton()
    doc.add_bone(data, "body", y=100)
    doc.add_bone(data, "upper", "body", length=100)
    doc.add_bone(data, "lower", "upper", x=100, length=100)
    for name, img_w in (("upper", 100), ("lower", lower_image.width)):
        doc.add_slot(data, name, name, attachment=name)
        x = 50 if name == "upper" else 100 - img_w / 2
        doc.set_attachment(data, name, name, att.region(img_w, lower_image.height if name == "lower" else 40, x, 0))
    doc.add_slot(data, "body", "body", attachment="body")
    doc.set_attachment(data, "body", "body", att.region(60, 60, 0, 0))  # covers the shoulder
    Image.new("RGBA", (60, 60), DARK).save(images / "body.png")
    doc.save(data, sk)
    return sk


def test_joint_cut_edge_to_edge_opens_a_gap_and_overlap_closes_it(tmp_path):
    butt = _limb(tmp_path, Image.new("RGBA", (100, 40), DARK))
    data = doc.load(butt)
    parts = art.load_images(tmp_path / "images")
    joints = art.check_joints(data, quality._Parts(parts))
    assert [j["where"] for j in joints] == ["upper > lower"]
    assert joints[0]["code"] == "joint_gap" and 0.05 < joints[0]["gap"] < 0.09 and joints[0]["overlap"] < 0.02
    assert "'lower'" in joints[0]["fix"] and "under 'upper'" in joints[0]["fix"]
    # The same sleeve drawn 20 px further back, under the upper one: nothing opens.
    overlap = _limb(tmp_path, Image.new("RGBA", (140, 40), DARK))
    assert art.check_joints(doc.load(overlap), quality._Parts(art.load_images(tmp_path / "images"))) == []


def test_joint_bridged_by_a_weighted_mesh_is_skipped(tmp_path):
    sk = _limb(tmp_path, Image.new("RGBA", (100, 40), DARK))
    data = doc.load(sk)
    mesh = att.grid_mesh(100, 40, 4, 1, 50, 0)
    mesh["vertices"] = att.auto_weights(data, "upper", mesh, ["upper", "lower"])
    doc.set_attachment(data, "upper", "upper", mesh)
    assert art.check_joints(data, quality._Parts(art.load_images(tmp_path / "images"))) == []


def test_image_drawn_larger_than_its_pixels(tmp_path):
    sk = _limb(tmp_path, Image.new("RGBA", (100, 40), DARK))
    data = doc.load(sk)
    doc.get_attachment(data, "lower", "lower").update(width=200, height=80)
    doc.get_attachment(data, "upper", "upper").update(width=100, height=44)
    issues = art.check_attachments(data, art.load_images(tmp_path / "images"))
    assert [(i["code"], i["where"]) for i in issues] == [("stretched", "upper/upper"), ("upscaled", "lower/lower")]


def test_check_art_tool_reports_and_shows_then_clean_art_fixes(tmp_path):
    src = tmp_path / "parts"
    src.mkdir()
    _disc().save(src / "tete.png")
    hard = _disc(antialiased=False)
    ImageDraw.Draw(hard).rectangle([3, 3, 8, 8], fill=DARK)
    hard.save(src / "bras.png")
    report, picture = asyncio.run(mcp.call_tool("check_art", {"images": str(src)}))
    info = json.loads(report.text)
    assert (info["checked"], info["parts_with_warnings"], info["warnings"]) == (2, 1, 2)
    assert [p["part"] for p in info["parts"]] == ["bras"]
    assert {i["code"] for i in info["parts"][0]["issues"]} == {"hard_edges", "fragments"}
    assert picture.type == "image" and info["verdict"].startswith("fix before rigging")

    with pytest.raises(ValueError, match="overwrite"):
        quality.clean_art(str(src), str(src))
    res = quality.clean_art(str(src), str(tmp_path / "clean"))
    assert res["written"] == 2 and res["warnings_left"] == 0
    assert res["changed"] == [{"part": "bras", "fragments_removed": {"count": 1, "px": 36}, "softened_px": 0.8}]
    assert Image.open(tmp_path / "clean" / "bras.png").size == (160, 160)
    again = quality.check_art(str(tmp_path / "clean"), return_image=False)
    assert again["warnings"] == 0 and again["verdict"].startswith("no defect measured")


# ------------------------------------------------------------ amplitude
def _sampled(tracks, n=61):
    times = [i / (n - 1) for i in range(n)]
    out = {}
    for bone, fn in tracks.items():
        pts = [fn(t) for t in times]
        out[bone] = {"x": [p[0] for p in pts], "y": [p[1] for p in pts], "rotation": [p[2] for p in pts],
                     "scaleX": [1.0] * n, "scaleY": [1.0] * n}
    return {"times": times, "tracks": out, "events": []}


def test_amplitude_tells_a_living_character_from_a_still_one():
    def still(x, y):
        return lambda t: (x, y, 0.0)

    wave = lambda t: (300 + 40 * math.sin(2 * math.pi * t), 300.0, 30 * math.sin(2 * math.pi * t))  # noqa: E731
    frozen = {f"b{i}": still(100 * i, 0) for i in range(7)}
    rep = analysis.motion_report(_sampled({**frozen, "hand": wave}), loop=True,
                                 drawn_bones={*frozen, "hand"})
    assert rep["amplitude"]["moving_pct"] == 12 and rep["amplitude"]["max_rotation_deg"] == 60
    assert rep["amplitude"]["still"] == sorted(frozen)
    assert [i["code"] for i in rep["issues"]] == ["timid_motion"]

    alive = {f"b{i}": (lambda t, i=i: (100 * i + 60 * math.sin(2 * math.pi * t + i), 30 * math.cos(2 * math.pi * t), 20 * math.sin(2 * math.pi * t)))
             for i in range(8)}
    rep = analysis.motion_report(_sampled(alive), loop=True, drawn_bones=set(alive))
    assert rep["amplitude"]["moving_pct"] == 100 and rep["issues"] == []
    # Bones without art (IK targets, controls) do not count.
    assert "amplitude" not in analysis.motion_report(_sampled(alive), loop=True)
