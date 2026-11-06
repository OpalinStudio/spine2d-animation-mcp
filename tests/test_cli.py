"""Spine CLI wrapper: executable discovery per OS and argument building.

A fake `Spine` executable records its arguments, so these tests run without
Spine installed (on macOS/Linux; the fake is a shell script)."""

import json
import stat
import sys
from pathlib import Path

import pytest

from spine2d_mcp.cli import spine_cli as cli

def test_windows_candidates_prefer_console_build():
    env = {"ProgramFiles": r"C:\Program Files", "ProgramFiles(x86)": r"C:\Program Files (x86)",
           "LOCALAPPDATA": r"C:\Users\me\AppData\Local", "USERPROFILE": r"C:\Users\me"}
    paths = [str(p).replace("/", "\\") for p in cli.candidate_paths("Windows", env)]
    assert paths[0].endswith(r"Program Files\Spine\Spine.com")
    assert any(p.endswith(r"Local\Programs\Spine\Spine.com") for p in paths)
    first_exe = next(i for i, p in enumerate(paths) if p.endswith(".exe"))
    assert all(p.endswith(".com") for p in paths[:first_exe])


def test_macos_candidates():
    paths = [p.as_posix() for p in cli.candidate_paths("Darwin", {"HOME": "/Users/me"})]
    assert paths[0] == "/Applications/Spine.app/Contents/MacOS/Spine"
    assert "/Users/me/Applications/Spine.app/Contents/MacOS/Spine" in paths


def test_linux_candidates():
    paths = [p.as_posix() for p in cli.candidate_paths("Linux", {"HOME": "/home/me"})]
    assert paths[0] == "/home/me/Spine/Spine.sh"
    assert "/opt/Spine/Spine.sh" in paths


def test_app_bundle_and_folder_are_normalized(tmp_path):
    app = tmp_path / "Spine.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    assert cli._normalize(app, "Darwin") == app / "Contents" / "MacOS" / "Spine"
    folder = tmp_path / "Spine"
    folder.mkdir()
    (folder / "Spine.com").write_text("")
    assert cli._normalize(folder, "Windows") == folder / "Spine.com"


def test_missing_spine_gives_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINE_EXE", str(tmp_path / "nope"))
    monkeypatch.setattr(cli, "candidate_paths", lambda *a, **k: [])
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(cli.SpineCliError, match="SPINE_EXE"):
        cli.find_spine()


@pytest.fixture
def fake_spine(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("fake exe is a shell script")
    log = tmp_path / "calls.jsonl"
    exe = tmp_path / "Spine"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print('Spine fake 4.3.26')\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SPINE_EXE", str(exe))
    monkeypatch.delenv("SPINE_VERSION", raising=False)

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()]

    return calls


def test_export_json_writes_settings_file(fake_spine, tmp_path):
    from spine2d_mcp.tools.cli import spine_export

    res = spine_export(str(tmp_path / "hero.spine"), str(tmp_path / "out"), format="json",
                       overrides={"prettyPrint": False})
    assert res["ok"] and "fake" in res["stdout"]
    args = fake_spine()[-1]
    assert args[0] == "-i" and args[1].endswith("hero.spine")
    assert args[2] == "-o" and args[4] == "-e" and args[5].endswith(".json")
    assert args[-2:] == ["--set", "prettyPrint=false"]
    assert not Path(args[5]).exists()  # temp settings cleaned up


def test_export_png_needs_skeleton_name(fake_spine, tmp_path):
    from spine2d_mcp.tools.cli import spine_export

    with pytest.raises(ValueError):
        spine_export("p.spine", "out", format="png")
    spine_export("p.spine", str(tmp_path), format="png", skeleton="hero", animation="walk", fps=24)
    assert fake_spine()[-1][4] == "-e"


def test_import_data_variants(fake_spine, tmp_path, monkeypatch):
    monkeypatch.setenv("SPINE_VERSION", "4.3.xx")
    cli.import_data("hero.json", "hero.spine", skeleton_name="hero", scale=0.5)
    a = fake_spine()[-1]
    assert a[:2] == ["-u", "4.3.xx"]
    # 4.3 syntax: -i <data> -s <scale> -o <project> --to <name> ... -r (last)
    assert a[2] == "-i" and a[4:6] == ["-s", "0.5"] and a[6] == "-o"
    assert a[-3:] == ["--to", "hero", "-r"]
    cli.import_data("anims.json", "hero.spine", skeleton_name="hero", import_animations=True, merge=True)
    assert fake_spine()[-1][-5:] == ["--to", "hero", "-a", "--merge", "-r"]
    cli.import_data("anims.json", "hero.spine", animation="walk")
    assert fake_spine()[-1][-3:] == ["-a", "walk", "-r"]
    cli.import_data("anims.json", "hero.spine", skeleton_name="hero", animation=["walk", "run"],
                    replace=True, from_skeleton="src")
    a = fake_spine()[-1]
    assert a[a.index("--from") + 1] == "src"
    assert a[-8:] == ["--to", "hero", "-a", "walk", "-a", "run", "--replace", "-r"]


def test_image_export_settings_classes():
    for kind, spec in cli.EDITOR_IMAGE_FORMATS.items():
        s = cli.image_export_settings(kind, "hero", "walk", scale=50, fps=24)
        assert s["class"] == spec["class"]
        assert s["skeleton"] == "hero" and s["animation"] == "walk" and s["animationType"] == "single"
        assert s["scale"] == 50 and s["fps"] == 24 and s["speed"] >= 1
    gif = cli.image_export_settings("gif", "hero")
    # Fields the 4.3.26 CLI requires for GIF (checked against the editor).
    assert gif["colors"] == 256 and gif["transparency"] is True and gif["animationType"] == "all"
    bg = cli.image_export_settings("png", "hero", background="#102030")
    assert bg["background"] == {"r": 0.0627, "g": 0.1255, "b": 0.1882, "a": 1.0}
    assert bg["transparent"] is False
    with pytest.raises(ValueError):
        cli.image_export_settings("psd", "hero")


def test_editor_render_imports_json_into_temp_project(fake_spine, tmp_path):
    from spine2d_mcp.cli.editor_render import EditorRenderError, editor_render

    sk = tmp_path / "hero.json"
    sk.write_text("{}")
    with pytest.raises(EditorRenderError):
        # The fake Spine writes nothing, so the import is reported as failed.
        editor_render(str(sk), str(tmp_path / "out.gif"), format="gif", animation="walk")
    call = fake_spine()[-1]
    assert call[:2] == ["-i", str(sk)] and call[-3:] == ["hero", "--replace", "-r"]
    assert "spine-editor-" in call[call.index("-o") + 1]  # throwaway project, not next to hero.json


def test_pack_unpack_clean_info(fake_spine, tmp_path):
    cli.pack("imgs", "out", name="hero", settings={"packing": "polygons"}, projects=["hero.spine"])
    a = fake_spine()[-1]
    assert a[0] == "-i" and "-j" in a and a[a.index("-n") + 1] == "hero" and "-p" in a
    cli.unpack("imgs", "out", "hero.atlas", project="hero.spine")
    assert fake_spine()[-1][-2] == "-c"
    cli.clean_up("hero.spine")
    assert fake_spine()[-1][-1] == "-m"
    cli.last_export_settings("hero.spine")
    assert fake_spine()[-1][-1] == "--last-export-settings"
    cli.info("hero.spine")
    assert len(fake_spine()[-1]) == 2


def test_status_reports_found(fake_spine):
    st = cli.status()
    assert st["found"] and st["executable"].endswith("Spine")


def test_settings_writers(tmp_path):
    from spine2d_mcp.tools.cli import write_export_settings

    out = write_export_settings(str(tmp_path / "png.json"), "png", {"skeleton": "hero", "animation": "run"})
    s = json.loads(Path(out["path"]).read_text())
    assert s["class"] == "export-png" and s["animation"] == "run" and s["animationType"] == "single"
    pk = cli.pack_settings(maxWidth=4096)
    assert pk["maxWidth"] == 4096 and pk["atlasExtension"] == ".atlas"
