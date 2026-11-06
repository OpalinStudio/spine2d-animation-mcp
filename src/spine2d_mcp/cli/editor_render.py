"""Render with the Spine editor itself (highest fidelity, the editor's own
renderer: MSAA, smoothing, physics warm-up...) from a skeleton JSON/binary or
a .spine project.

JSON / .skel input is imported into a THROWAWAY project in a temp folder
(`--to <name> --replace -r`), so the user's .spine files are never modified.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import spine_cli as cli

_SKEL_RE = re.compile(r"^\s*Skeleton:\s*(.+?)\s*$", re.M)


class EditorRenderError(RuntimeError):
    pass


def project_skeletons(project: str, spine_path: str | None = None) -> list[str]:
    res = cli.info(project, spine_path)
    return _SKEL_RE.findall(res.stdout)


def _clean_log(text: str, n: int = 12) -> list[str]:
    keep = [ln for ln in text.splitlines()
            if ln.strip() and not ln.startswith("   ") and "MSAA" not in ln and "NoSuchMethod" not in ln
            and not ln.startswith(("Spine Launcher", "Esoteric Software", "Mac OS", "Licensed to"))]
    return keep[-n:]


def _probe(path: Path) -> dict:
    out: dict = {"bytes": path.stat().st_size}
    try:
        from PIL import Image

        with Image.open(path) as im:
            out.update(size=list(im.size), frames=getattr(im, "n_frames", 1), mode=im.mode)
            return out
    except Exception:
        pass
    ff = shutil.which("ffprobe")
    if ff:
        p = subprocess.run([ff, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                            "stream=codec_name,width,height,pix_fmt,nb_read_packets", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=120)
        parts = p.stdout.strip().split(",")
        if len(parts) >= 5:
            out.update(codec=parts[0], size=[int(parts[1]), int(parts[2])], pix_fmt=parts[3],
                       frames=int(parts[4]) if parts[4].isdigit() else None)
    return out


def editor_render(
    input_path: str,
    output: str,
    format: str = "png",
    animation: str | None = None,
    skin: str | None = None,
    skeleton_name: str | None = None,
    scale: float = 100,
    fps: float = 30,
    background: str | None = None,
    warm_up: int = 0,
    last_frame: bool = False,
    max_bounds: bool = True,
    pose: bool = False,
    settings_overrides: dict | None = None,
    spine_path: str | None = None,
    version: str | None = None,
    timeout: float = 1800,
) -> dict:
    if format not in cli.EDITOR_IMAGE_FORMATS:
        raise EditorRenderError(f"format must be one of {sorted(cli.EDITOR_IMAGE_FORMATS)}")
    src = Path(input_path).expanduser().resolve()
    if not src.exists():
        raise EditorRenderError(f"not found: {src}")
    fmt = cli.EDITOR_IMAGE_FORMATS[format]
    out = Path(output).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="spine-editor-") as tmp_s:
        tmp = Path(tmp_s)
        import_log: list[str] = []
        if src.suffix.lower() == ".spine":
            project = src
            names = project_skeletons(str(project), spine_path)
            if skeleton_name is None:
                if len(names) != 1:
                    raise EditorRenderError(f"project has skeletons {names}: pass skeleton_name")
                skeleton_name = names[0]
            elif names and skeleton_name not in names:
                raise EditorRenderError(f"skeleton {skeleton_name!r} not in project ({names})")
        else:
            skeleton_name = skeleton_name or re.sub(r"[^\w\-]+", "_", src.stem)
            project = tmp / f"{skeleton_name}.spine"
            r = cli.import_data(str(src), str(project), skeleton_name=skeleton_name, replace=True,
                                spine_path=spine_path, version_=version)
            import_log = _clean_log(r.stdout + r.stderr)
            if not r.ok or not project.exists():
                raise EditorRenderError(f"import into a temp project failed: {import_log}")
        settings = cli.image_export_settings(
            format, skeleton_name, animation=None if pose else animation, skin=skin, scale=scale,
            fps=fps, background=background, warm_up=warm_up, last_frame=last_frame,
            max_bounds=max_bounds, export_type="pose" if pose else "animation",
        )
        if settings_overrides:
            settings.update(settings_overrides)
        if fmt["sequence"]:
            out.mkdir(parents=True, exist_ok=True)
            target = out / skeleton_name
            before = set(out.iterdir())
        else:
            target = out if out.suffix else out.with_suffix(fmt["ext"])
            target.parent.mkdir(parents=True, exist_ok=True)
            before = set()
        r = cli.export(str(project), str(target), settings, spine_path=spine_path, version_=version,
                       timeout=timeout)
        log = _clean_log(r.stdout + r.stderr)
        if fmt["sequence"]:
            files = sorted(p for p in out.iterdir() if p not in before and p.is_file())
        else:
            files = [target] if target.exists() else []
        files = [f for f in files if f.stat().st_size > 0]
        if not r.ok or not files:
            if not fmt["sequence"] and target.exists() and target.stat().st_size == 0:
                target.unlink()
            raise EditorRenderError(f"Spine export failed: {log}")
    info = _probe(files[0])
    return {
        "output": str(out if fmt["sequence"] else files[0]),
        "files": [str(f) for f in files][:400],
        "file_count": len(files),
        "format": format,
        "skeleton": skeleton_name,
        "first_file": info,
        "editor_log": log,
        **({"import_log": import_log} if import_log else {}),
    }
