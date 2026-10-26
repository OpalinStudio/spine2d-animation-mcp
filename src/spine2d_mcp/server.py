"""FastMCP server for Spine 4.3: rigging, animation, preview and Spine CLI
tools. The tools live in `spine2d_mcp.tools.*`; this module wires them up."""

from __future__ import annotations

from .tools import mcp
from .tools.assets import import_psd_to_spine  # noqa: F401  (re-export, used by tests)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
