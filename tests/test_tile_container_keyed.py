"""analyze_animation: a symbol clip that keys the bone carrying the reel-cell
tile (background / frame / cell mask) moves the tile out of its cell."""

import pytest

from spine2d_mcp.spine import analysis
from spine2d_mcp.spine import animation as an
from spine2d_mcp.spine import document as doc


def _tile_rig(with_tile: bool = True) -> dict:
    data = doc.new_skeleton()
    doc.add_bone(data, "centre", "root")
    doc.add_bone(data, "perso", "centre", y=-20)
    doc.add_bone(data, "tete", "perso", y=60)
    if with_tile:
        doc.add_slot(data, "fond", "centre", attachment="fond")
        doc.add_slot(data, "cadre", "centre", attachment="cadre")
    doc.add_slot(data, "corps", "perso", attachment="corps")
    doc.add_slot(data, "visage", "tete", attachment="visage")
    return data


def _key(data, anim, bone, timeline, keys):
    an.set_keys(doc.animations(data).setdefault(anim, {}), "bone", bone, timeline, keys)


def _issues(data, anim, code="tile_container_keyed"):
    return [i for i in analysis.analyze(data, anim)["issues"] if i["code"] == code]


def test_pop_on_the_tile_container_is_reported_with_the_character_bone():
    data = _tile_rig()
    _key(data, "win", "centre", "scale", [
        {"x": 1, "y": 1, "curve": "easeOut"}, {"time": 0.2, "x": 1.3, "y": 1.3, "curve": "easeInOut"},
        {"time": 0.6, "x": 1, "y": 1}])
    found = _issues(data, "win")
    assert len(found) == 1
    issue = found[0]
    assert issue["severity"] == "info"
    assert issue["where"].startswith("centre")
    assert "fond" in issue["message"] and "cadre" in issue["message"]
    assert "1.3" in issue["message"]
    assert "perso" in issue["fix"]


@pytest.mark.parametrize("timeline, keys", [
    ("translate", [{"x": 0, "y": 0}, {"time": 0.1, "x": 6, "y": 0}, {"time": 0.2, "x": 0, "y": 0}]),
    ("rotate", [{"value": 0}, {"time": 0.2, "value": 5}, {"time": 0.4, "value": 0}]),
    ("scaley", [{"value": 1}, {"time": 0.2, "value": 0.9}, {"time": 0.4, "value": 1}]),
    ("shearx", [{"value": 0}, {"time": 0.2, "value": 4}, {"time": 0.4, "value": 0}]),
])
def test_every_transform_timeline_on_the_container_counts(timeline, keys):
    data = _tile_rig()
    _key(data, "clip", "centre", timeline, keys)
    assert len(_issues(data, "clip")) == 1


def test_keys_on_the_character_are_fine():
    data = _tile_rig()
    _key(data, "win", "perso", "scale", [
        {"x": 1, "y": 1, "curve": "easeOut"}, {"time": 0.2, "x": 1.08, "y": 1.08, "curve": "easeInOut"},
        {"time": 0.6, "x": 1, "y": 1}])
    assert _issues(data, "win") == []


def test_no_tile_slots_no_issue():
    data = _tile_rig(with_tile=False)
    _key(data, "win", "centre", "scale", [{"x": 1, "y": 1}, {"time": 0.2, "x": 1.3, "y": 1.3},
                                          {"time": 0.6, "x": 1, "y": 1}])
    assert _issues(data, "win") == []


def test_setup_valued_keys_on_the_container_do_not_count():
    data = _tile_rig()
    _key(data, "hold", "centre", "scale", [{"x": 1, "y": 1}, {"time": 0.5, "x": 1, "y": 1}])
    _key(data, "hold", "centre", "translate", [{"x": 0, "y": 0}])
    assert _issues(data, "hold") == []


def test_window_whose_frame_is_the_moving_object_is_not_reported():
    # Intro window / multiplier plate: the frame IS the object, no character
    # subtree apart from it, so moving it in and out is the point.
    data = doc.new_skeleton()
    doc.add_bone(data, "plaque", "root")
    doc.add_slot(data, "cadre", "plaque", attachment="cadre")
    doc.add_slot(data, "texte", "plaque", attachment="texte")
    _key(data, "in", "plaque", "translate", [{"x": -300, "y": 0}, {"time": 0.3, "x": 0, "y": 0}])
    assert _issues(data, "in") == []
