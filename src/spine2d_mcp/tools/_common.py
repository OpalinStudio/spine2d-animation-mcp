"""Shared helpers for the MCP tool modules."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..guide import SERVER_INSTRUCTIONS
from ..spine import document as doc
from ..spine.validator import ValidationReport

mcp = FastMCP("spine2d-mcp", instructions=SERVER_INSTRUCTIONS)

# Tools that only read: clients can run them without asking.
READ_ONLY = ToolAnnotations(readOnlyHint=True)


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
