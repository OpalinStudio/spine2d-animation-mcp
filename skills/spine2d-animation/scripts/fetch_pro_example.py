#!/usr/bin/env python3
"""Download official Esoteric Software Spine 4.3 professional examples on demand
into the local spine2d-mcp cache (never into the git repository) for study,
benchmarking, and inspection with spine2d-mcp tools.

Usage:
    python3 fetch_pro_example.py --list
    python3 fetch_pro_example.py spineboy
    python3 fetch_pro_example.py 7-anticipation --force

License notice:
    Downloaded files come from https://github.com/EsotericSoftware/spine-runtimes
    (branch 4.3) and remain subject to Esoteric Software's license terms
    (Spine Runtimes License / non-commercial example assets). Use them strictly
    for learning, reference, and testing — never commit or ship them in games.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import urllib.error
import urllib.request
from pathlib import Path

REF = "4.3"
RAW_BASE = f"https://raw.githubusercontent.com/EsotericSoftware/spine-runtimes/{REF}/examples"

# Curated catalog verified against EsotericSoftware/spine-runtimes branch 4.3.
# Each entry maps key -> (category, repo_dir, json_files, atlas_file, summary)
CATALOG: dict[str, tuple[str, str, list[str], str, str]] = {
    # --- Animation Principles Masterclass (8-part Esoteric series) ---
    "1-weight-and-mass": (
        "principles",
        "1-weight-and-mass",
        ["1-weight-and-mass-balls-ess.json", "1-weight-and-mass-drop-ess.json"],
        "1-weight-and-mass.atlas",
        "Weight & mass contrast via bounce decay and spacing",
    ),
    "2-the-12-principles": (
        "principles",
        "2-the-12-principles",
        ["2-the-12-principles-ess.json"],
        "2-the-12-principles.atlas",
        "Basketball, billiard, bowling & tennis balls (79-99% Bezier)",
    ),
    "3-timing-and-spacing": (
        "principles",
        "3-timing-and-spacing",
        ["3-timing-and-spacing-ess.json"],
        "3-timing-and-spacing.atlas",
        "Heavy (5.33s) vs light (1.67s) timing & spacing study",
    ),
    "4-wave-principle": (
        "principles",
        "4-wave-principle",
        ["4-wave-principle-ess.json"],
        "4-wave-principle.atlas",
        "Overlapping wave chains (wave-offset vs wave-by-hand)",
    ),
    "5-squash-and-stretch": (
        "principles",
        "5-squash-and-stretch",
        ["5-squash-and-stretch-ess.json"],
        "5-squash-and-stretch.atlas",
        "Ball + full expressive character ('speedy', 94% Bezier)",
    ),
    "6-arcs": (
        "principles",
        "6-arcs",
        ["6-arcs-pro.json"],
        "6-arcs.atlas",
        "Smooth curved motion arcs with transform constraints (97% Bezier)",
    ),
    "7-anticipation": (
        "principles",
        "7-anticipation",
        ["sack-pro.json"],
        "7-anticipation.atlas",
        "Flour sack anticipation, walk (98% Bezier) & 20 physics constraints",
    ),
    "8-follow-through": (
        "principles",
        "8-follow-through",
        ["8-follow-through-pro-ball.json", "8-follow-through-pro-pendulum.json"],
        "8-follow-through.atlas",
        "Follow-through & damped settle (ball + pendulum, 94-99% Bezier)",
    ),
    # --- Production Character & Spine 4.3 Feature Rigs ---
    "spineboy": (
        "production",
        "spineboy",
        ["spineboy-pro.json"],
        "spineboy.atlas",
        "Canonical 2D action hero: IK, idle/run/jump/shoot/aim/transitions",
    ),
    "celestial-circus": (
        "production",
        "celestial-circus",
        ["celestial-circus-pro.json"],
        "celestial-circus.atlas",
        "Official Physics showcase: 30 physics constraints, hair/cloth/wind + eyeblink",
    ),
    "diamond": (
        "production",
        "diamond",
        ["diamond-pro.json"],
        "diamond.atlas",
        "Official Spine 4.3 Slider showcase: bone-driven faux-3D rotation",
    ),
    "owl": (
        "production",
        "owl",
        ["owl-pro.json"],
        "owl.atlas",
        "2.5D head turn poses (up/down/left/right) + 10 feather physics constraints",
    ),
    "mix-and-match": (
        "production",
        "mix-and-match",
        ["mix-and-match-pro.json"],
        "mix-and-match.atlas",
        "Modular character with 34 skins, linked meshes, IK/path/transform",
    ),
    "raptor": (
        "production",
        "raptor",
        ["raptor-pro.json"],
        "raptor.atlas",
        "Heavy creature IK walk/roar/jump + surgical 3-bone Track-1 overlays",
    ),
    "hero": (
        "production",
        "hero",
        ["hero-pro.json"],
        "hero.atlas",
        "Action knight with path cape, melee attack, run, fall transitions",
    ),
    "cloud-pot": (
        "production",
        "cloud-pot",
        ["cloud-pot.json"],
        "cloud-pot.atlas",
        "Soft-body physics (26 physics constraints driven by 1-5 animated bones)",
    ),
    "snowglobe": (
        "production",
        "snowglobe",
        ["snowglobe-pro.json"],
        "snowglobe.atlas",
        "Clipping dome + 47 physics constraints (idle, shake, eyeblink)",
    ),
    "chibi-stickers": (
        "production",
        "chibi-stickers",
        ["chibi-stickers.json"],
        "chibi-stickers.atlas",
        "11 skins + snappy UI/emote library (angry, excited, crying, flushed...)",
    ),
    "stretchyman": (
        "production",
        "stretchyman",
        ["stretchyman-pro.json"],
        "stretchyman.atlas",
        "Elastic cartoon limbs with IK + Path constraints (sneak)",
    ),
    "coin": (
        "production",
        "coin",
        ["coin-pro.json"],
        "coin.atlas",
        "Compact faux-3D spinning pickup / slot-style coin with mesh & draw order",
    ),
}


def default_cache_root() -> Path:
    env = os.environ.get("SPINE_MCP_CACHE")
    if env:
        return Path(env).expanduser()
    sys_name = platform.system()
    if sys_name == "Darwin":
        return Path.home() / "Library" / "Caches" / "spine2d-mcp"
    if sys_name == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "spine2d-mcp"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".cache") / "spine2d-mcp"


def download(url: str, dst: Path, force: bool = False) -> bool:
    if dst.exists() and not force:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "spine2d-mcp-skill"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dst)
    return True


def parse_atlas_pages(atlas_text: str) -> list[str]:
    """Return image filenames referenced by a Spine/libgdx .atlas file."""
    pages: list[str] = []
    for raw in atlas_text.splitlines():
        line = raw.strip()
        if not line or ":" in line or line.startswith(" "):
            continue
        if line.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
            pages.append(line)
    return pages


def fetch_example(name: str, out_root: Path, force: bool = False) -> dict:
    if name not in CATALOG:
        known = ", ".join(sorted(CATALOG))
        raise SystemExit(f"Unknown example {name!r}. Available: {known}")
    category, repo_dir, json_files, atlas_file, summary = CATALOG[name]
    dest = out_root / name
    dest.mkdir(parents=True, exist_ok=True)

    downloaded: list[Path] = []
    # 1. Atlas + all its referenced PNG pages
    atlas_url = f"{RAW_BASE}/{repo_dir}/export/{atlas_file}"
    atlas_dst = dest / atlas_file
    if download(atlas_url, atlas_dst, force):
        downloaded.append(atlas_dst)
    pages = parse_atlas_pages(atlas_dst.read_text(encoding="utf-8", errors="replace"))
    for page in pages:
        p_dst = dest / page
        if download(f"{RAW_BASE}/{repo_dir}/export/{page}", p_dst, force):
            downloaded.append(p_dst)

    # 2. Skeleton JSON(s)
    json_paths: list[Path] = []
    for jf in json_files:
        j_dst = dest / jf
        if download(f"{RAW_BASE}/{repo_dir}/export/{jf}", j_dst, force):
            downloaded.append(j_dst)
        json_paths.append(j_dst)

    # 3. Optional license.txt
    lic_dst = dest / "license.txt"
    try:
        if download(f"{RAW_BASE}/{repo_dir}/license.txt", lic_dst, force):
            downloaded.append(lic_dst)
    except urllib.error.HTTPError:
        pass

    return {
        "name": name,
        "category": category,
        "summary": summary,
        "dir": str(dest),
        "skeletons": [str(p) for p in json_paths],
        "atlas": str(atlas_dst),
        "pages": pages,
        "downloaded_now": len(downloaded),
    }


def print_catalog() -> None:
    for cat, title in (
        ("principles", "Animation Principles Masterclass (Esoteric Software, Spine 4.3)"),
        ("production", "Production Character & Feature Rigs (Esoteric Software, Spine 4.3)"),
    ):
        print(f"\n{title}")
        print("-" * len(title))
        for key, (c, _, jsons, _, summary) in CATALOG.items():
            if c == cat:
                print(f"  {key:22s}  {summary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch official Esoteric Software Spine 4.3 pro examples into the local cache."
    )
    parser.add_argument("examples", nargs="*", help="Example name(s) from --list")
    parser.add_argument("--list", action="store_true", help="List all available pro examples")
    parser.add_argument("--out", type=Path, default=None, help="Override cache directory")
    parser.add_argument("--force", action="store_true", help="Re-download existing cached files")
    args = parser.parse_args(argv)

    if args.list or not args.examples:
        print_catalog()
        return 0

    out_root = args.out.expanduser() if args.out else default_cache_root() / "pro-examples"
    for name in args.examples:
        info = fetch_example(name, out_root, force=args.force)
        sk = info["skeletons"][0]
        at_arg = (
            f', atlas="{info["atlas"]}"'
            if Path(sk).stem != Path(info["atlas"]).stem
            else ""
        )
        print(f"\n[{info['name']}] {info['summary']}")
        print(f"  Folder   : {info['dir']}")
        print(f"  Skeleton : {', '.join(info['skeletons'])}")
        print(f"  Atlas    : {info['atlas']} ({len(info['pages'])} page(s))")
        print("  Next with spine2d-mcp:")
        print(f'    inspect_skeleton(skeleton="{sk}", section="summary")')
        print(f'    analyze_animation(skeleton="{sk}")')
        print(f'    runtime_render(skeleton="{sk}"{at_arg}, output="{info["dir"]}/debug.png", format="png", debug=True)')
    print(
        "\nLicense reminder: Esoteric Software example assets are for study/reference only "
        "(Spine Runtimes / non-commercial license). Do not commit or ship them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
