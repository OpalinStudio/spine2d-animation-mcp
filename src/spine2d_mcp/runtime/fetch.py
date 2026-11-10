"""Download the official Spine web runtimes (spine-webgl, spine-player) from
npm into a local cache, on first use.

The runtimes are NOT vendored in this repository: they are covered by the
Spine Runtimes License (each user needs their own Spine Editor license), so
they are fetched from the official `@esotericsoftware/*` npm packages, checked
against the registry's sha512 integrity, and kept in the user's cache:

- `SPINE_MCP_CACHE` if set, else
- macOS `~/Library/Caches/spine2d-mcp`, Windows `%LOCALAPPDATA%/spine2d-mcp`,
  Linux `$XDG_CACHE_HOME/spine2d-mcp` (default `~/.cache/spine2d-mcp`).

`SPINE_RUNTIME_VERSION` picks the version: an exact version ("4.3.13") or a
`major.minor` line ("4.3", the default), resolved to the newest published
patch of that line. The runtime major.minor must match the editor that
exported the data (4.3 data -> 4.3 runtime).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import platform
import re
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REGISTRY = "https://registry.npmjs.org"
DEFAULT_LINE = "4.3"

# package -> files to keep (path inside the npm tarball -> name in the cache)
PACKAGES: dict[str, dict[str, str]] = {
    "spine-webgl": {
        "package/dist/iife/spine-webgl.js": "spine-webgl.js",
    },
    "spine-player": {
        "package/dist/iife/spine-player.min.js": "spine-player.min.js",
        "package/dist/spine-player.css": "spine-player.css",
    },
}
LICENSE_URL = "https://raw.githubusercontent.com/EsotericSoftware/spine-runtimes/{branch}/LICENSE"


class RuntimeFetchError(RuntimeError):
    pass


def cache_root() -> Path:
    env = os.environ.get("SPINE_MCP_CACHE")
    if env:
        return Path(env).expanduser()
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Caches" / "spine2d-mcp"
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "spine2d-mcp"
    return Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "spine2d-mcp"


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "spine2d-mcp"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https only)
        return r.read()


def requested_version() -> str:
    return os.environ.get("SPINE_RUNTIME_VERSION", DEFAULT_LINE).strip()


def _cached_versions(line: str) -> list[str]:
    root = cache_root() / "runtimes"
    if not root.is_dir():
        return []
    out = [p.name for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    out = [v for v in out if v == line or v.startswith(line + ".")]
    return sorted(out, key=_vkey)


def resolve_version(spec: str | None = None) -> str:
    """Exact version, or newest published patch of a major.minor line."""
    spec = spec or requested_version()
    if spec.count(".") >= 2:
        return spec
    meta = json.loads(_get(f"{REGISTRY}/@esotericsoftware%2Fspine-webgl"))
    versions = [v for v in meta.get("versions", {}) if v.startswith(spec + ".") and "-" not in v]
    if not versions:
        raise RuntimeFetchError(f"no published spine-webgl version for line {spec}")
    return max(versions, key=_vkey)


@dataclass
class Runtime:
    version: str
    dir: Path

    @property
    def webgl_js(self) -> Path:
        return self.dir / "spine-webgl.js"

    @property
    def player_js(self) -> Path:
        return self.dir / "spine-player.min.js"

    @property
    def player_css(self) -> Path:
        return self.dir / "spine-player.css"

    @property
    def license(self) -> Path:
        return self.dir / "LICENSE-spine-runtimes.txt"

    def as_dict(self) -> dict:
        return {"version": self.version, "dir": str(self.dir),
                "files": sorted(p.name for p in self.dir.iterdir())}


def _download_package(name: str, version: str, dest: Path) -> None:
    meta = json.loads(_get(f"{REGISTRY}/@esotericsoftware%2F{name}/{version}"))
    dist = meta["dist"]
    blob = _get(dist["tarball"], timeout=300)
    integrity = dist.get("integrity", "")
    if integrity.startswith("sha512-"):
        digest = base64.b64encode(hashlib.sha512(blob).digest()).decode()
        if digest != integrity[len("sha512-"):]:
            raise RuntimeFetchError(f"integrity check failed for {name}@{version}")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member, target in PACKAGES[name].items():
            f = tar.extractfile(member)
            if f is None:
                raise RuntimeFetchError(f"{member} missing from {name}@{version}")
            (dest / target).write_bytes(f.read())


def ensure_runtime(spec: str | None = None, offline_ok: bool = True) -> Runtime:
    """Return the cached runtime for `spec`, downloading it if needed. When
    the registry can't be reached, fall back to the newest cached version of
    the same line."""
    spec = spec or requested_version()
    try:
        version = resolve_version(spec)
    except Exception as e:  # network down, registry error...
        cached = _cached_versions(spec if spec.count(".") < 2 else ".".join(spec.split(".")[:2]))
        if offline_ok and cached:
            version = cached[-1]
        else:
            raise RuntimeFetchError(f"cannot resolve Spine runtime {spec}: {e}") from e
    d = cache_root() / "runtimes" / version
    if (d / "manifest.json").exists():
        return Runtime(version, d)
    d.mkdir(parents=True, exist_ok=True)
    try:
        for name in PACKAGES:
            _download_package(name, version, d)
        branch = ".".join(version.split(".")[:2])
        try:
            (d / "LICENSE-spine-runtimes.txt").write_bytes(_get(LICENSE_URL.format(branch=branch)))
        except Exception:
            (d / "LICENSE-spine-runtimes.txt").write_text(
                "Spine Runtimes License Agreement - https://esotericsoftware.com/spine-runtimes-license\n"
            )
    except Exception as e:
        raise RuntimeFetchError(f"cannot download Spine runtime {version}: {e}") from e
    (d / "manifest.json").write_text(json.dumps({"version": version, "packages": list(PACKAGES)}))
    return Runtime(version, d)
