"""Serialize a SpineProject to a Spine 4.3 skeleton JSON file.

The Spine editor's reader applies the same defaults documented in
`schema.py`, and rejects redundant default-valued fields, so we dump with
`exclude_defaults=True`. `by_alias` is on for forward-compatibility if aliases
are introduced later; today field names already match the wire format.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import SpineProject


def to_dict(project: SpineProject) -> dict:
    out = project.model_dump(
        by_alias=True,
        exclude_defaults=True,
        exclude_none=True,
        mode="json",
    )
    # The `skeleton.spine` version is how the editor selects its reader, so it
    # must always be present even when the rest of the header is default.
    # exclude_defaults would drop the whole header, so emit it explicitly.
    out["skeleton"] = project.skeleton.model_dump(
        by_alias=True, exclude_defaults=True, exclude_none=True, mode="json"
    )
    out["skeleton"].setdefault("spine", project.skeleton.spine)
    # Skin `name` is read without a default (getString("name")), so the
    # "default" skin must keep its name even though it equals the model default.
    for skin, model in zip(out.get("skins", []), project.skins):
        skin["name"] = model.name
        skin.setdefault("attachments", {})
        out_skin = {"name": skin.pop("name"), **skin}
        skin.clear()
        skin.update(out_skin)
    # Constraint `type` is required by the 4.3 reader even though "ik" is the
    # model default, so exclude_defaults must not drop it.
    if project.constraints:
        out["constraints"] = [
            {"type": c.type, **c.model_dump(by_alias=True, exclude_defaults=True,
                                            exclude_none=True, mode="json")}
            for c in project.constraints
        ]
    return out


def write_json(project: SpineProject, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(project), indent=2), encoding="utf-8")
    return path
