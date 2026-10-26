import pytest

from spine2d_mcp.psd.parser import parse_psd
from spine2d_mcp.spine.builder import build
from spine2d_mcp.spine.schema import (
    Bone,
    IkConstraint,
    RegionAttachment,
    Skin,
    Slot,
    SpineProject,
)
from spine2d_mcp.spine.validator import SpineValidationError, validate


def test_valid_project_passes(synthetic_psd):
    # build() already validates; this just confirms it doesn't raise.
    build(parse_psd(synthetic_psd))


def test_slot_without_bone_fails():
    proj = SpineProject(
        bones=[Bone(name="root")],
        slots=[Slot(name="head", bone="missing", attachment="head")],
    )
    with pytest.raises(SpineValidationError, match="missing bone"):
        validate(proj)


def test_parent_declared_after_child_fails():
    proj = SpineProject(
        bones=[Bone(name="child", parent="parent"), Bone(name="parent")],
    )
    with pytest.raises(SpineValidationError, match="not declared before"):
        validate(proj)


def test_duplicate_bone_name_fails():
    proj = SpineProject(bones=[Bone(name="root"), Bone(name="root")])
    with pytest.raises(SpineValidationError, match="duplicate bone"):
        validate(proj)


def test_ik_missing_target_fails():
    proj = SpineProject(
        bones=[Bone(name="root"), Bone(name="a", parent="root")],
        constraints=[IkConstraint(name="k", bones=["a"], target="ghost")],
    )
    with pytest.raises(SpineValidationError, match="target"):
        validate(proj)


def test_attachment_to_missing_slot_fails():
    proj = SpineProject(
        bones=[Bone(name="root")],
        skins=[Skin(attachments={"nope": {"a": RegionAttachment(width=1, height=1)}})],
    )
    with pytest.raises(SpineValidationError, match="missing slot"):
        validate(proj)


def test_43_format_rules_on_raw_data():
    from spine2d_mcp.spine.validator import validate_data

    data = {
        "skeleton": {"spine": "4.3.00"},
        "bones": [{"name": "root"}, {"name": "a", "parent": "root"}],
        "constraints": [
            {"type": "physics", "name": "same", "bone": "a", "rotate": 1},
            {"type": "transform", "name": "same", "source": "root", "bones": ["a"],
             "properties": {"rotate": {"to": {"rotate": {}}}}},
        ],
        "skins": [{"name": "default"}],
    }
    # Constraint names are unique per type, like SkeletonData.findConstraint.
    assert validate_data(data).ok
    data["constraints"].append({"type": "physics", "name": "same", "bone": "a", "rotate": 1})
    assert "duplicate physics constraint" in " ".join(validate_data(data).errors)


@pytest.mark.skipif("SPINE_EXAMPLES_DIR" not in __import__("os").environ,
                    reason="set SPINE_EXAMPLES_DIR to spine-runtimes/examples (4.3 branch)")
def test_official_43_examples_validate():
    """Every skeleton exported by Spine 4.3 in spine-runtimes/examples must
    pass (guards against false positives)."""
    import json
    import os
    from pathlib import Path

    from spine2d_mcp.spine.validator import validate_data

    files = [p for p in Path(os.environ["SPINE_EXAMPLES_DIR"]).glob("*/export/*.json")
             if not p.name.startswith("atlas")]
    assert files
    for p in files:
        report = validate_data(json.loads(p.read_text(encoding="utf-8")))
        assert report.ok, (p.name, report.errors[:3])
