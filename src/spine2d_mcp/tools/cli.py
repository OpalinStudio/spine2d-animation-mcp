"""MCP tools: drive the installed Spine editor through its command line
(macOS, Windows, Linux). Needs Spine Essential/Professional installed and
activated; see `spine_status` for where the executable is looked up."""

from __future__ import annotations

from typing import Any, Literal

from ..cli import spine_cli as cli
from ._common import mcp, resolve


@mcp.tool()
def spine_status(spine_path: str | None = None, check_version: bool = False) -> dict:
    """Locate the Spine executable on this machine (macOS / Windows / Linux)
    and report the environment (SPINE_EXE, SPINE_VERSION, SPINE_ARGS).
    check_version runs `Spine --version`."""
    out = cli.status(spine_path)
    if check_version and out.get("found"):
        out["version"] = cli.version(spine_path).as_dict()
    return out


@mcp.tool()
def spine_cli_help(advanced: bool = False, spine_path: str | None = None) -> dict:
    """Print the installed Spine CLI help (`--help`, or `--advanced`), the
    authoritative list of flags for the user's exact editor version."""
    return cli.help_text(advanced, spine_path).as_dict(limit=20000)


@mcp.tool()
def spine_export(
    input_path: str,
    output: str,
    format: Literal["json", "binary", "json+pack", "binary+pack", "png", "settings"] = "json",
    settings: str | dict | None = None,
    clean_up: bool = False,
    nonessential: bool = True,
    pretty: bool = True,
    skeleton: str | None = None,
    animation: str | None = None,
    skin: str | None = None,
    scale: float = 100,
    fps: float = 30,
    overrides: dict[str, Any] | None = None,
    spine_path: str | None = None,
    version: str | None = None,
) -> dict:
    """Export with the Spine editor: `Spine -i <input> -o <output> -e ...`.

    input_path: a .spine project (or a folder of projects, wildcards allowed
    in 4.3). format:
    - json / binary: skeleton data (nonessential keeps editor data),
      json+pack / binary+pack also pack the atlas;
    - png: PNG frames of `animation` (all animations if omitted) of
      `skeleton` (the skeleton name in the project), at `scale` % and `fps`;
    - settings: any export settings JSON (path or dict), e.g. one saved from
      the Spine export dialog for GIF, WebM, MP4, MOV, AVI, HTML (Spine
      Player / Web Components) or a custom JSON/binary export.
    clean_up runs animation clean up first. overrides become `--set key=value`
    (4.3) to tweak settings without editing the file (e.g. {"scale": 50})."""
    if format in ("json", "binary"):
        export: str | dict = (
            cli.json_export_settings(nonessential, pretty) if format == "json"
            else cli.binary_export_settings(nonessential)
        )
    elif format == "png":
        if not skeleton:
            raise ValueError("png export needs `skeleton` (the skeleton name inside the project)")
        export = cli.png_export_settings(skeleton, animation, skin, scale, fps)
    elif format == "settings":
        if settings is None:
            raise ValueError("format 'settings' needs `settings` (path or dict)")
        export = settings if isinstance(settings, dict) else str(resolve(settings))
    else:
        export = format
    return cli.export(input_path, output, export, clean_up, overrides, spine_path, version).as_dict()


@mcp.tool()
def spine_import_data(
    input_path: str,
    project: str,
    skeleton_name: str | None = None,
    scale: float | None = None,
    animation: str | None = None,
    import_all_animations: bool = False,
    merge: bool = False,
    extra_args: list[str] | None = None,
    spine_path: str | None = None,
    version: str | None = None,
) -> dict:
    """Import skeleton data (JSON / .skel / another .spine / a folder) into a
    .spine project, created if missing: the way to turn the JSON built with
    these tools into a project you open in Spine 4.3.

    skeleton_name renames the imported skeleton. 4.3 options: `animation`
    (import that animation into the existing skeleton `skeleton_name`),
    import_all_animations (`-a` without name), merge (`--merge` into the
    existing skeleton). Check spine_cli_help if your editor build differs."""
    return cli.import_data(
        input_path, project, skeleton_name, scale, animation, import_all_animations, merge,
        extra_args or (), spine_path, version,
    ).as_dict()


@mcp.tool()
def spine_pack(
    images_dir: str,
    output_dir: str,
    name: str | None = None,
    settings: str | dict | None = None,
    projects: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
    spine_path: str | None = None,
) -> dict:
    """Pack images with Spine's texture packer (`-i -o -n -p`). settings: a
    pack settings JSON path, or a dict of overrides on sensible defaults
    (e.g. {"packing": "polygons", "premultiplyAlpha": true, "maxWidth": 4096,
    "scale": [1, 0.5], "scaleSuffix": ["", "@0.5x"]}). projects (`-j`): the
    .spine projects whose meshes enable polygon packing / per-skin atlases."""
    return cli.pack(images_dir, output_dir, name, settings, projects or (), overrides, spine_path).as_dict()


@mcp.tool()
def spine_unpack(
    images_dir: str, output_dir: str, atlas: str, project: str | None = None,
    spine_path: str | None = None,
) -> dict:
    """Unpack a texture atlas back to images with Spine (`-c`), restoring
    polygon-packed images when the project (`-j`) is given."""
    return cli.unpack(images_dir, output_dir, atlas, project, spine_path).as_dict()


@mcp.tool()
def spine_clean_up(project: str, spine_path: str | None = None) -> dict:
    """Run animation clean up on every animation of a .spine project (or a
    folder of projects) and save it (`-i <project> -m`)."""
    return cli.clean_up(project, spine_path).as_dict()


@mcp.tool()
def spine_project_info(input_path: str, spine_path: str | None = None) -> dict:
    """Print information about a project or data file (skeletons, animations,
    version...) via `Spine -i <path>`."""
    return cli.info(input_path, spine_path).as_dict(limit=20000)


@mcp.tool()
def spine_last_export_settings(project: str, spine_path: str | None = None) -> dict:
    """4.3: write the project's most recent export settings to a
    `.export.json` file next to it (reuse it with spine_export
    format="settings")."""
    return cli.last_export_settings(project, spine_path).as_dict()


@mcp.tool()
def spine_cli(args: list[str], spine_path: str | None = None, version: str | None = None,
              timeout: float = 1800) -> dict:
    """Run the Spine CLI with raw arguments (anything the other tools don't
    cover), e.g. ["-i", "/p/hero.spine", "-o", "/out", "-e", "/p/webm.json"].
    Arguments are passed without a shell, so paths with spaces are fine."""
    return cli.run(args, spine_path=spine_path, version=version, timeout=timeout).as_dict(limit=20000)


@mcp.tool()
def write_export_settings(
    path: str,
    kind: Literal["json", "binary", "png", "pack"],
    options: dict[str, Any] | None = None,
) -> dict:
    """Write an export / pack settings JSON file to reuse with spine_export
    (format="settings") or spine_pack. kind png needs options.skeleton."""
    o = dict(options or {})
    if kind == "json":
        s = cli.json_export_settings(**o)
    elif kind == "binary":
        s = cli.binary_export_settings(**o)
    elif kind == "png":
        if "skeleton" not in o:
            raise ValueError("png settings need options.skeleton")
        s = cli.png_export_settings(**o)
    else:
        s = cli.pack_settings(**o)
    p = cli.write_settings(s, resolve(path))
    return {"path": str(p), "settings": s}
