"""Cross-platform wrapper around the Spine editor command line interface.

The Spine editor (Essential/Professional/Enterprise, here 4.3) doubles as a
headless CLI: export JSON/binary/images/video, import data into a project,
pack/unpack texture atlases, run animation clean up, print project info.
Reference: https://esotericsoftware.com/spine-command-line-interface and the
4.3 changelog (import/merge animations, `--set`, wildcards, `SPINE_ARGS`,
`--last-export-settings`, HTML export...).

Executable discovery, in order:
1. the `spine_path` argument of a tool call,
2. the `SPINE_EXE` (or `SPINE_PATH`) environment variable: the executable,
   the install folder, or on macOS the `Spine.app` bundle,
3. the platform default install locations:
   - Windows: `%ProgramFiles%\\Spine\\Spine.com` (console build, preferred for
     the CLI), `%ProgramFiles(x86)%\\Spine\\Spine.com`,
     `%LOCALAPPDATA%\\Programs\\Spine\\Spine.com`, then `Spine.exe`
   - macOS: `/Applications/Spine.app/Contents/MacOS/Spine`,
     `~/Applications/Spine.app/Contents/MacOS/Spine`
   - Linux: `~/Spine/Spine.sh`, `/opt/Spine/Spine.sh`
4. `Spine`/`Spine.com`/`Spine.sh` on the PATH.

`SPINE_VERSION` (e.g. "4.3.xx" or "4.3.26") is passed as `-u <version>` so
every run uses the same editor version as the user's projects.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


class SpineCliError(RuntimeError):
    pass


def _system() -> str:
    return platform.system()  # "Windows", "Darwin", "Linux"


def candidate_paths(system: str | None = None, env: dict | None = None) -> list[Path]:
    system = system or _system()
    env = os.environ if env is None else env
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    out: list[Path] = []
    if system == "Windows":
        roots = [
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramW6432", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        local = env.get("LOCALAPPDATA")
        dirs = [Path(r) / "Spine" for r in roots]
        if local:
            dirs.append(Path(local) / "Programs" / "Spine")
        dirs.append(home / "Spine")
        for d in dirs:
            out.append(d / "Spine.com")
        for d in dirs:
            out.append(d / "Spine.exe")
    elif system == "Darwin":
        out += [
            Path("/Applications/Spine.app/Contents/MacOS/Spine"),
            home / "Applications" / "Spine.app" / "Contents" / "MacOS" / "Spine",
        ]
    else:
        out += [home / "Spine" / "Spine.sh", Path("/opt/Spine/Spine.sh"), Path("/usr/local/Spine/Spine.sh")]
    # De-duplicate while keeping order.
    seen, uniq = set(), []
    for p in out:
        k = str(p).lower() if system == "Windows" else str(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _normalize(p: Path, system: str) -> Path:
    """Accept an install folder or a macOS .app bundle and return the binary."""
    if p.suffix == ".app" or (p.is_dir() and p.name.endswith(".app")):
        return p / "Contents" / "MacOS" / "Spine"
    if p.is_dir():
        for name in ("Spine.com", "Spine.exe", "Spine.sh", "Spine"):
            if (p / name).exists():
                return p / name
        if (p / "Spine.app").exists():
            return p / "Spine.app" / "Contents" / "MacOS" / "Spine"
    return p


def find_spine(explicit: str | None = None) -> Path:
    system = _system()
    tried: list[str] = []
    for value in (explicit, os.environ.get("SPINE_EXE"), os.environ.get("SPINE_PATH")):
        if value:
            p = _normalize(Path(os.path.expanduser(value)), system)
            if p.exists():
                return p
            tried.append(str(p))
    for p in candidate_paths(system):
        if p.exists():
            return p
        tried.append(str(p))
    for name in ("Spine.com", "Spine", "Spine.sh", "spine"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SpineCliError(
        "Spine executable not found. Set SPINE_EXE to the Spine executable "
        "(Windows: C:\\Program Files\\Spine\\Spine.com, macOS: "
        "/Applications/Spine.app/Contents/MacOS/Spine). Tried: " + "; ".join(tried)
    )


@dataclass
class CliResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_dict(self, limit: int = 6000) -> dict:
        def cut(s: str) -> str:
            return s if len(s) <= limit else "...(truncated)...\n" + s[-limit:]

        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "command": self.command,
            "stdout": cut(self.stdout),
            "stderr": cut(self.stderr),
        }


def run(
    args: Sequence[str],
    spine_path: str | None = None,
    version: str | None = None,
    timeout: float = 900,
    cwd: str | None = None,
    check: bool = False,
) -> CliResult:
    exe = find_spine(spine_path)
    cmd = [str(exe)]
    version = version or os.environ.get("SPINE_VERSION")
    if version and "-u" not in args and "--update" not in args:
        cmd += ["-u", version]
    cmd += [str(a) for a in args]
    kwargs: dict[str, Any] = {}
    if _system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    except subprocess.TimeoutExpired as e:
        raise SpineCliError(f"Spine CLI timed out after {timeout}s: {' '.join(cmd)}") from e
    except OSError as e:
        raise SpineCliError(f"could not start Spine ({exe}): {e}") from e
    res = CliResult(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")
    if check and not res.ok:
        raise SpineCliError(f"Spine CLI failed ({res.returncode}): {res.stderr or res.stdout}")
    return res


def _abs(p: str | os.PathLike) -> str:
    return str(Path(os.path.expanduser(str(p))).resolve())


def _set_args(overrides: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    for k, v in (overrides or {}).items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif v is None:
            v = "null"
        out += ["--set", f"{k}={v}"]
    return out


# ------------------------------------------------------------ settings JSON
def json_export_settings(nonessential: bool = True, pretty: bool = True, **extra: Any) -> dict:
    """Export settings for JSON data (fields as in spine-runtimes
    examples/export/json.json, written by the 4.3 editor)."""
    return {"class": "json", "extension": ".json", "format": "JSON",
            "nonessential": nonessential, "prettyPrint": pretty, **extra}


def binary_export_settings(nonessential: bool = True, **extra: Any) -> dict:
    return {"class": "binary", "extension": ".skel", "nonessential": nonessential, **extra}


def pack_settings(**overrides: Any) -> dict:
    """Texture packer settings (keys as written by the 4.3 editor, see
    examples/export/atlas-1.0.json). Notable 4.3 options: `packing`
    ("rectangles" | "polygons"), `bruteForce`, per-skin atlases."""
    base = {
        "pot": False,
        "paddingX": 2,
        "paddingY": 2,
        "edgePadding": True,
        "duplicatePadding": False,
        "rotation": True,
        "minWidth": 16,
        "minHeight": 16,
        "maxWidth": 2048,
        "maxHeight": 2048,
        "square": False,
        "stripWhitespaceX": True,
        "stripWhitespaceY": True,
        "alphaThreshold": 3,
        "filterMin": "Linear",
        "filterMag": "Linear",
        "wrapX": "ClampToEdge",
        "wrapY": "ClampToEdge",
        "format": "RGBA8888",
        "alias": True,
        "outputFormat": "png",
        "jpegQuality": 0.9,
        "ignoreBlankImages": True,
        "fast": False,
        "debug": False,
        "silent": False,
        "combineSubdirectories": False,
        "flattenPaths": False,
        "premultiplyAlpha": False,
        "useIndexes": True,
        "bleed": True,
        "limitMemory": True,
        "grid": False,
        "packing": "rectangles",
        "scale": [1],
        "scaleSuffix": [""],
        "scaleResampling": ["bicubic"],
        "atlasExtension": ".atlas",
        "prettyPrint": True,
    }
    base.update(overrides)
    return base


def png_export_settings(
    skeleton: str,
    animation: str | None = None,
    skin: str | None = None,
    scale: float = 100,
    fps: float = 30,
    background: str | None = None,
    pack_atlas: bool = False,
    **extra: Any,
) -> dict:
    """PNG sequence export (fields from examples/export/png-0.5-frame-by-
    frame.json). `animation=None` exports every animation."""
    settings: dict[str, Any] = {
        "class": "export-png",
        "exportType": "animation",
        "skeletonType": "single",
        "skeleton": skeleton,
        "animationType": "single" if animation else "all",
        "animation": animation,
        "skinType": "single" if skin else "current",
        "skinNone": False,
        "skin": skin,
        "maxBounds": False,
        "renderImages": True,
        "renderBones": False,
        "renderOthers": False,
        "scale": scale,
        "fitWidth": 0,
        "fitHeight": 0,
        "enlarge": False,
        "background": background,
        "fps": fps,
        "lastFrame": False,
        "cropWidth": 0,
        "cropHeight": 0,
        "rangeStart": -1,
        "rangeEnd": -1,
        "msaa": 4,
        "smoothing": 8,
        "renderSelection": False,
        "cropX": 0,
        "cropY": 0,
        "open": False,
    }
    if pack_atlas:
        settings["packAtlas"] = pack_settings(premultiplyAlpha=True)
    settings.update(extra)
    return settings


def write_settings(settings: dict, path: str | Path | None = None) -> Path:
    if path is None:
        fd, name = tempfile.mkstemp(prefix="spine-settings-", suffix=".json")
        os.close(fd)
        path = name
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return p


# --------------------------------------------------------------- commands
def version(spine_path: str | None = None) -> CliResult:
    return run(["--version"], spine_path=spine_path, timeout=120)


def help_text(advanced: bool = False, spine_path: str | None = None) -> CliResult:
    return run(["--advanced" if advanced else "--help"], spine_path=spine_path, timeout=120)


def export(
    input_path: str,
    output: str,
    export: str | dict = "json",
    clean: bool = False,
    overrides: dict[str, Any] | None = None,
    spine_path: str | None = None,
    version_: str | None = None,
    timeout: float = 1800,
) -> CliResult:
    """`Spine -i <project> -o <out> -e <settings.json | json | binary |
    json+pack | binary+pack>`. A dict is written to a temp settings file."""
    tmp = None
    if isinstance(export, dict):
        tmp = write_settings(export)
        export_arg = str(tmp)
    elif export in ("json", "binary", "json+pack", "binary+pack"):
        export_arg = export
    else:
        export_arg = _abs(export)
    args = ["-i", _abs(input_path), "-o", _abs(output)]
    if clean:
        args.append("-m")
    args += ["-e", export_arg]
    args += _set_args(overrides)
    try:
        return run(args, spine_path=spine_path, version=version_, timeout=timeout)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def import_data(
    input_path: str,
    project: str,
    skeleton_name: str | None = None,
    scale: float | None = None,
    animation: str | None = None,
    import_animations: bool = False,
    merge: bool = False,
    extra_args: Iterable[str] = (),
    spine_path: str | None = None,
    version_: str | None = None,
    timeout: float = 900,
) -> CliResult:
    """Import JSON/binary/project data into a .spine project (created if it
    doesn't exist): `Spine -i <data> -o <project.spine> -r [name]`.

    4.3 additions: `animation` / `import_animations` (`-a [name]`, import one
    or all animations into an existing skeleton) and `merge` (`--merge`)."""
    args = ["-i", _abs(input_path), "-o", _abs(project)]
    if scale is not None:
        args += ["-s", str(scale)]
    if animation or import_animations:
        # Target skeleton in the project, then the animation(s) to import.
        if skeleton_name:
            args += ["-r", skeleton_name]
        args += ["-a"] + ([animation] if animation else [])
    else:
        args += ["-r"] + ([skeleton_name] if skeleton_name else [])
    if merge:
        args.append("--merge")
    args += list(extra_args)
    return run(args, spine_path=spine_path, version=version_, timeout=timeout)


def pack(
    input_dir: str,
    output_dir: str,
    name: str | None = None,
    settings: str | dict | None = None,
    projects: Sequence[str] = (),
    overrides: dict[str, Any] | None = None,
    spine_path: str | None = None,
    timeout: float = 900,
) -> CliResult:
    tmp = None
    if isinstance(settings, dict):
        tmp = write_settings(pack_settings(**settings))
        pack_arg = str(tmp)
    elif settings:
        pack_arg = _abs(settings)
    else:
        tmp = write_settings(pack_settings())
        pack_arg = str(tmp)
    args = ["-i", _abs(input_dir)]
    for p in projects:
        args += ["-j", _abs(p)]
    args += ["-o", _abs(output_dir)]
    if name:
        args += ["-n", name]
    args += ["-p", pack_arg]
    args += _set_args(overrides)
    try:
        return run(args, spine_path=spine_path, timeout=timeout)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def unpack(
    input_dir: str,
    output_dir: str,
    atlas: str,
    project: str | None = None,
    spine_path: str | None = None,
    timeout: float = 900,
) -> CliResult:
    args = ["-i", _abs(input_dir), "-o", _abs(output_dir)]
    if project:
        args += ["-j", _abs(project)]
    args += ["-c", _abs(atlas)]
    return run(args, spine_path=spine_path, timeout=timeout)


def clean_up(project: str, spine_path: str | None = None, timeout: float = 900) -> CliResult:
    return run(["-i", _abs(project), "-m"], spine_path=spine_path, timeout=timeout)


def info(input_path: str, spine_path: str | None = None, timeout: float = 300) -> CliResult:
    return run(["-i", _abs(input_path)], spine_path=spine_path, timeout=timeout)


def last_export_settings(project: str, spine_path: str | None = None, timeout: float = 300) -> CliResult:
    """4.3: writes `<project>.export.json` from the project's last export."""
    return run(["-i", _abs(project), "--last-export-settings"], spine_path=spine_path, timeout=timeout)


def status(spine_path: str | None = None) -> dict:
    """Where Spine was found (or why not), plus the platform defaults."""
    system = _system()
    out: dict[str, Any] = {
        "platform": system,
        "machine": platform.machine(),
        "env": {k: os.environ.get(k) for k in ("SPINE_EXE", "SPINE_PATH", "SPINE_VERSION", "SPINE_ARGS")},
        "candidates": [str(p) for p in candidate_paths(system)],
    }
    try:
        out["executable"] = str(find_spine(spine_path))
        out["found"] = True
    except SpineCliError as e:
        out["found"] = False
        out["error"] = str(e)
    return out
