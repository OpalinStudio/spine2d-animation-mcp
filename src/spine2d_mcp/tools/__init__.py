"""MCP tool modules. Importing this package registers every tool on the
shared FastMCP instance (`_common.mcp`)."""

from . import animation, assets, cli, skeleton  # noqa: F401
from ._common import mcp

__all__ = ["mcp"]
