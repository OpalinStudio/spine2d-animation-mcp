"""Export a skeleton as an HTML preview using the official Spine Web Player.

`single_file=True` (default) writes ONE self-contained .html: the player JS
and CSS, the skeleton, the atlas and its pages are inlined (the player's
`rawDataURIs`), so the file can be sent to a phone and opened offline.
`single_file=False` writes a folder (index.html + assets/).

The page adds big buttons for each animation and skin (handy on a phone),
a background switcher (dark / light / checker / game color) and a speed
control. It sets `window.__spineMcpStatus` to "ok" or "error: ..." so a
headless check can verify it actually plays.

The Spine Runtimes License requires the license notice to travel with the
runtime: it is embedded in the page (and written next to it in folder mode).
"""

from __future__ import annotations

import base64
import html
import json
import shutil
from pathlib import Path

from ..atlas.reader import read_atlas
from .fetch import ensure_runtime
from .render import RuntimeRenderError, resolve_inputs, runtime_line_for

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".json": "application/json", ".atlas": "text/plain", ".skel": "application/octet-stream"}

TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
__CSS__
<style>
  :root { --bg: __BG__; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: #eee;
    font: 15px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { display: flex; flex-direction: column; }
  #stage { flex: 1; min-height: 55vh; position: relative; }
  #player { position: absolute; inset: 0; }
  body.checker #stage { background: repeating-conic-gradient(#bbb 0 25%, #888 0 50%) 0 0 / 24px 24px; }
  #panel { padding: 10px 12px calc(10px + env(safe-area-inset-bottom)); background: rgba(0,0,0,.55);
    display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .row[hidden] { display: none; }
  .row b { min-width: 74px; font-weight: 600; opacity: .8; }
  button { background: #2c2f36; color: #fff; border: 1px solid #555; border-radius: 10px;
    padding: 9px 13px; font-size: 15px; }
  button.on { background: #e0a526; color: #111; border-color: #e0a526; }
  #status { font-size: 12px; opacity: .7; }
</style>
</head>
<body>
<div id="stage"><div id="player"></div></div>
<div id="panel">
  <div class="row" id="anims"><b>Animation</b></div>
  <div class="row" id="skins" hidden><b>Skin</b></div>
  <div class="row"><b>Fond</b>
    <button data-bg="__BG__">Jeu</button><button data-bg="#111318">Sombre</button>
    <button data-bg="#f2f2f2">Clair</button><button data-bg="checker">Damier</button></div>
  <div class="row"><b>Vitesse</b>
    <button data-speed="0.25">x0.25</button><button data-speed="0.5">x0.5</button>
    <button data-speed="1" class="on">x1</button><button data-speed="2">x2</button>
    <button id="loop" class="on">Boucle</button></div>
  <div id="status">__TITLE__ · Spine Web Player __VERSION__</div>
</div>
__JS__
<script type="text/plain" id="spine-runtimes-license">
__LICENSE__
</script>
<script>
(function () {
  var CFG = __CONFIG__;
  var loop = true, player = null, current = CFG.animation;
  function mark(sel, el) { document.querySelectorAll(sel).forEach(function (b) { b.classList.toggle("on", b === el); }); }
  function play(name) {
    if (!player || !player.animationState) return;
    current = name;
    player.animationState.setAnimation(0, name, loop);
    player.play();
  }
  CFG.player.success = function (p) {
    player = p;
    var data = p.skeleton.data;
    var box = document.getElementById("anims");
    data.animations.forEach(function (a) {
      var b = document.createElement("button");
      b.textContent = a.name + " (" + a.duration.toFixed(2) + "s)";
      b.onclick = function () { play(a.name); mark("#anims button", b); };
      if (a.name === current) b.classList.add("on");
      box.appendChild(b);
    });
    if (data.skins.length > 1) {
      var sbox = document.getElementById("skins"); sbox.hidden = false;
      data.skins.forEach(function (s) {
        var b = document.createElement("button"); b.textContent = s.name;
        b.onclick = function () { p.skeleton.setSkin(s.name); p.skeleton.setupPoseSlots(); mark("#skins button", b); };
        sbox.appendChild(b);
      });
    }
    window.__spineMcpStatus = "ok";
  };
  CFG.player.error = function (p, msg) {
    window.__spineMcpStatus = "error: " + msg;
    document.getElementById("status").textContent = "Erreur : " + msg;
  };
  document.querySelectorAll("[data-bg]").forEach(function (b) {
    b.onclick = function () {
      var v = b.getAttribute("data-bg");
      document.body.classList.toggle("checker", v === "checker");
      document.documentElement.style.setProperty("--bg", v === "checker" ? "#777" : v);
      mark("[data-bg]", b);
    };
  });
  document.querySelectorAll("[data-speed]").forEach(function (b) {
    b.onclick = function () { if (player) player.speed = parseFloat(b.getAttribute("data-speed")); mark("[data-speed]", b); };
  });
  document.getElementById("loop").onclick = function () {
    loop = !loop; this.classList.toggle("on", loop); if (current) play(current);
  };
  try { new spine.SpinePlayer("player", CFG.player); }
  catch (e) { window.__spineMcpStatus = "error: " + e; }
})();
</script>
</body>
</html>
"""


def _data_uri(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def export_web_preview(
    skeleton: str,
    output: str,
    atlas: str | None = None,
    animation: str | None = None,
    skin: str | None = None,
    background: str = "#1b1d22",
    title: str | None = None,
    single_file: bool = True,
    show_controls: bool = True,
    padding: str = "8%",
    runtime_version: str | None = None,
) -> dict:
    out = Path(output).expanduser().resolve()
    work = out.parent if single_file else out
    work.mkdir(parents=True, exist_ok=True)
    sk, at, how = resolve_inputs(skeleton, atlas, work / ".spine-preview-tmp")
    rt = ensure_runtime(runtime_line_for(sk, runtime_version))
    pages = [at.parent / p.name for p in read_atlas(at).pages]
    for p in pages:
        if not p.is_file():
            raise RuntimeRenderError(f"atlas page missing: {p}")
    if animation is None and sk.suffix.lower() == ".json":
        anims = list((json.loads(sk.read_text(encoding="utf-8")).get("animations") or {}).keys())
        animation = anims[0] if anims else None
    sk_name, at_name = sk.name, at.name
    player_cfg: dict = {
        "skeleton": sk_name, "atlas": at_name, "showControls": show_controls,
        "alpha": True, "backgroundColor": "#00000000", "preserveDrawingBuffer": False,
        "viewport": {"padLeft": padding, "padRight": padding, "padTop": padding, "padBottom": padding},
    }
    if animation:
        player_cfg["animation"] = animation
    if skin:
        player_cfg["skin"] = skin
    title = title or sk.stem
    lic = rt.license.read_text(encoding="utf-8", errors="replace") if rt.license.exists() else ""
    if single_file:
        raw = {sk_name: _data_uri(sk), at_name: _data_uri(at)}
        for p in pages:
            raw[p.name] = _data_uri(p)
        player_cfg["rawDataURIs"] = raw
        css = f"<style>{rt.player_css.read_text(encoding='utf-8')}</style>"
        js = f"<script>{rt.player_js.read_text(encoding='utf-8')}</script>"
        html_path = out if out.suffix.lower() in (".html", ".htm") else out.with_suffix(".html")
        files = [html_path]
    else:
        assets = out / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        for f in [sk, at, *pages]:
            shutil.copy2(f, assets / f.name)
        shutil.copy2(rt.player_js, out / rt.player_js.name)
        shutil.copy2(rt.player_css, out / rt.player_css.name)
        if rt.license.exists():
            shutil.copy2(rt.license, out / "LICENSE-spine-runtimes.txt")
        player_cfg["skeleton"] = f"assets/{sk_name}"
        player_cfg["atlas"] = f"assets/{at_name}"
        css = f'<link rel="stylesheet" href="{rt.player_css.name}">'
        js = f'<script src="{rt.player_js.name}"></script>'
        html_path = out / "index.html"
        files = [html_path, *(assets / f.name for f in [sk, at, *pages])]
    page = (TEMPLATE
            .replace("__TITLE__", html.escape(title))
            .replace("__BG__", background)
            .replace("__VERSION__", rt.version)
            .replace("__CSS__", css)
            .replace("__LICENSE__", html.escape(lic))
            .replace("__CONFIG__", json.dumps({"animation": animation, "player": player_cfg}))
            .replace("__JS__", js))
    html_path.write_text(page, encoding="utf-8")
    tmp = work / ".spine-preview-tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "html": str(html_path),
        "files": [str(f) for f in files],
        "size_bytes": html_path.stat().st_size,
        "single_file": single_file,
        "animation": animation,
        "runtime": f"spine-player {rt.version}",
        "atlas_source": how if how == "atlas" else "packed",
    }
