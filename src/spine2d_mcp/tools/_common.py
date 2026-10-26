"""Shared helpers for the MCP tool modules."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from mcp.server.fastmcp import FastMCP

from ..spine import document as doc
from ..spine.validator import ValidationReport

mcp = FastMCP(
    "spine2d-mcp",
    instructions=(
        "Spine 4.3 (Essential/Professional) animation toolkit. Skeletons are "
        "Spine JSON files on disk: every editing tool takes `skeleton` (path to "
        "the .json), applies one change, validates against the 4.3 format and "
        "saves (an invalid result is rejected and the file is left untouched). "
        "Typical flow: import_psd_to_spine or create_skeleton -> bones / slots / "
        "attachments / constraints -> animations (set_keyframes, "
        "generate_animation) -> render_preview to look at the result -> "
        "spine_import_data to build a .spine project, spine_export for runtime "
        "files. Call spine_reference for the format cheat sheet (timelines, "
        "curves, constraints). Coordinates are Spine's: y-up, bone-local, "
        "rotations in degrees counter-clockwise."
    ),
)


def resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


@dataclass
class Edit:
    path: Path
    data: dict
    report: ValidationReport = field(default_factory=ValidationReport)

    def result(self, **extra: Any) -> dict:
        out: dict[str, Any] = {"skeleton": str(self.path), **extra}
        if self.report.warnings:
            out["warnings"] = self.report.warnings
        return out


@contextmanager
def editing(skeleton: str, validate: bool = True) -> Iterator[Edit]:
    """Load -> yield for in-place edits -> validate & save (atomic)."""
    path = resolve(skeleton)
    ed = Edit(path, doc.load(path))
    yield ed
    ed.report = doc.save(ed.data, path, validate=validate)


def drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}
