"""Tests for the 2.2 features: new widget blocks, app targets, panels, visualizer frames, profiles, community themes."""
import copy
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def palette(tf, name="Tokyo Night"):
    return copy.deepcopy(tf.PRESETS[name])


# ── widget blocks ──────────────────────────────────────────────────

def helper_ns(tf):
    ns = {}
    exec(compile(tf.HELPER_SRC.replace("print(main(sys.argv[1:]))", ""), "tf-helper", "exec"), ns)
    return ns


def test_helper_reads_cpu_temperature_from_hwmon(tf):
    ns = helper_ns(tf)
    files = {"/sys/class/hwmon/hwmon0/name": "nvme", "/sys/class/hwmon/hwmon0/temp1_input": "40000",
             "/sys/class/hwmon/hwmon1/name": "k10temp", "/sys/class/hwmon/hwmon1/temp1_input": "61000",
             "/sys/class/hwmon/hwmon1/temp1_label": "Tccd1", "/sys/class/hwmon/hwmon1/temp2_input": "52250",
             "/sys/class/hwmon/hwmon1/temp2_label": "Tctl"}

    class FakeGlob:
        @staticmethod
        def glob(pattern):
            import fnmatch
            return sorted({k.rsplit("/", 1)[0] if pattern.endswith("hwmon*") else k for k in files
                           if fnmatch.fnmatch(k.rsplit("/", 1)[0] if pattern.endswith("hwmon*") else k, pattern)})
    ns["glob"] = FakeGlob
    ns["read"] = files.get
    assert ns["main"](["cputemp", "c"]) == "52°C"            # prefers the Tctl sensor
    assert ns["main"](["cputemp", "f"]) == "126°F"
    ns["shutil"] = type("S", (), {"which": staticmethod(lambda n: None)})
    assert ns["main"](["gpu", "usage"]) == "n/a"
    assert ns["main"](["gpu", "usage-raw"]) == "0"


def test_helper_calendar_highlights_today(tf):
    import datetime
    out = helper_ns(tf)["main"](["calendar", "monday", "1", "left"])
    lines = out.splitlines()
    assert lines[1].startswith("${color3}Mo Tu We Th Fr Sa Su")
    assert ("${color1}%2d${color0}" % datetime.date.today().day) in out


def test_helper_script_runs_standalone(tf, home):
    tf.ensure_helper()
    out = subprocess.run([sys.executable, str(tf.HELPER_PATH), "calendar", "sunday", "1", "center"],
                         capture_output=True, text=True).stdout
    assert "${alignc}" in out and "Su Mo Tu" in out


def test_network_block_has_no_arrow_glyphs_and_graphs_have_width(tf):
    w = tf.widget_template("system")
    cfg = tf.conky_config(w, palette(tf))
    assert "↓" not in cfg and "↑" not in cfg
    assert "Download" in cfg and "Upload" in cfg
    assert f"cpugraph cpu0 28,{w['width']} " in cfg


def test_old_network_blocks_get_new_labels(tf):
    w = tf.normalize_widget({"blocks": [{"type": "network", "label": "Net", "iface": "", "style": "graph"}]})
    assert w["blocks"][0]["label_down"] == "Download"


# ── app targets ────────────────────────────────────────────────────

def test_discord_css_has_old_and_new_variable_names(tf):
    css = tf.discord_css(palette(tf))
    assert "--background-primary: #1a1b26 !important" in css
    assert "--background-base-low:" in css and "--text-default:" in css
    assert css.count("{") == css.count("}")
    assert "@name ThemeForge" in css


def test_discord_only_writes_for_installed_clients(tf, home):
    (home / ".config" / "vesktop").mkdir(parents=True)
    tf.apply_discord(palette(tf), {}, lambda *_: None)
    assert (home / ".config/vesktop/themes/themeforge.theme.css").exists()
    assert not (home / ".config/Vencord").exists()


def test_btop_selects_theme_once(tf, home):
    conf = home / ".config/btop/btop.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text('color_theme = "Default"\ntheme_background = False\n')
    for _ in range(2):
        tf.apply_btop(palette(tf), {}, lambda *_: None)
    text = conf.read_text()
    assert text.count("color_theme") == 1 and 'color_theme = "themeforge"' in text
    assert 'theme[main_bg]="#1a1b26"' in (home / ".config/btop/themes/themeforge.theme").read_text()


def test_starship_edit_is_idempotent_and_valid(tf):
    original = '"$schema" = "x"\npalette = "mine"\n\n[character]\nsuccess_symbol = "[>](purple)"\n'
    once = tf.starship_toml(original, palette(tf))
    assert tf.starship_toml(once, palette(tf)) == once
    if sys.version_info >= (3, 11):
        import tomllib
        d = tomllib.loads(once)
        assert d["palette"] == "themeforge" and d["palettes"]["themeforge"]["purple"] == "#bb9af7"
        assert d["character"]["success_symbol"] == "[>](purple)"


def test_spicetify_and_vivaldi_exports(tf, home):
    ini = tf.spicetify_colors(palette(tf))
    assert "[themeforge]" in ini and "#" not in ini.split("]", 1)[1]
    tf.apply_vivaldi(palette(tf), {}, lambda *_: None)
    with zipfile.ZipFile(tf.EXPORT_DIR / "ThemeForge-vivaldi.zip") as z:
        data = json.loads(z.read("settings.json"))
    assert data["colorAccentBg"] == "#7aa2f7" and data["colorBg"] == "#1a1b26"


def test_papirus_folder_color_matching(tf):
    assert tf.nearest_papirus_color("#7aa2f7") == "blue"
    assert tf.nearest_papirus_color("#e25252") == "red"
    assert tf.nearest_papirus_color("#a6e3a1") in ("green", "teal")
    assert tf.nearest_papirus_color("#ffffff") == "white"


def test_icon_themes_skip_cursor_only_themes(tf, home):
    icons = home / ".local/share/icons"
    (icons / "Papirus").mkdir(parents=True)
    (icons / "Papirus/index.theme").write_text("[Icon Theme]\nName=Papirus\nDirectories=16x16/apps\n")
    (icons / "Bibata").mkdir()
    (icons / "Bibata/index.theme").write_text("[Icon Theme]\nName=Bibata\n")
    found = tf.installed_icon_themes()
    assert "Papirus" in found and "Bibata" not in found


# ── panels and visualizers ─────────────────────────────────────────

def test_launcher_items_read_desktop_files(tf, home):
    games = home / "Games"
    games.mkdir()
    (games / "trove.desktop").write_text("[Desktop Entry]\nName=Trove\nIcon=steam_icon_304050\nExec=steam x\n")
    (games / "hidden.desktop").write_text("[Desktop Entry]\nName=Hidden\nNoDisplay=true\n")
    (games / ".dotfile").write_text("")
    (games / "notes.txt").write_text("hi")
    items = tf.launcher_items("~/Games")
    assert [(i["name"], i["type"]) for i in items] == [("notes.txt", "file"), ("Trove", "desktop")]
    assert items[1]["icon"] == "steam_icon_304050"
    assert tf.desktop_exec_command({"Exec": "steam %U --flag %%"}) == "steam  --flag %"


def test_panel_layout_and_hits(tf):
    from PySide6.QtCore import QPointF
    p = tf.panel_template("launcher")
    lay, full = tf.panel_layout(p, 9)
    assert len(lay["items"]) == 9
    assert full.height() == p["padding"] * 2 + 26 + 3 * (p["icon_size"] + 32)
    assert tf.panel_hit(p, 9, lay["items"][5].center()) == ("item", 5)
    n = tf.panel_template("nowplaying")
    lay, _ = tf.panel_layout(n)
    assert tf.panel_hit(n, 0, lay["play"].center()) == ("play", None)
    kind, frac = tf.panel_hit(n, 0, QPointF(lay["progress"].left() + lay["progress"].width() / 4,
                                            lay["progress"].center().y()))
    assert kind == "seek" and abs(frac - 0.25) < 0.01


def test_now_playing_parsing(tf, home):
    np = tf.parse_np("Playing\tDoof Doof\tS3RL\tfile:///tmp/a.png\t214000000\t30500000\tspotify\n")
    assert np["title"] == "Doof Doof" and np["length"] == 214.0 and np["position"] == 30.5
    assert tf.parse_np("No players found") is None
    art = home / "cover.png"
    art.write_bytes(b"x")
    assert tf.fetch_art(art.as_uri()) == art
    assert tf.fetch_art("") is None
    assert tf.fmt_time(3725) == "1:02:05" and tf.fmt_time(65) == "1:05"


def test_frame_visualizer_hugs_its_panel(tf):
    from PySide6.QtCore import QRectF
    screen = QRectF(0, 0, 1920, 1080)
    panel = tf.panel_template("nowplaying")
    v = tf.vis_template("frame")
    v["wrap"] = panel["id"]
    g = tf.vis_geometry(v, screen, [panel])
    pr = tf.panel_rect(panel, screen)
    d = v["depth"] + 4
    assert g == pr.adjusted(-d, -d, d, d)
    v["wrap"] = "missing"
    assert tf.vis_geometry(v, screen, [panel]).width() == v["width"]


def test_bass_level(tf):
    assert tf.bass_level([1.0] * 2 + [0.0] * 18) == 1.0
    stereo = [0.0] * 9 + [1.0, 1.0] + [0.0] * 9
    assert tf.bass_level(stereo, stereo=True) == 1.0


# ── profiles ───────────────────────────────────────────────────────

def test_profiles_save_and_cycle(tf, home, monkeypatch):
    monkeypatch.setattr(tf, "running_state", lambda s: {"widgets": ["w1"], "visualizers": [], "panels": ["p1"],
                                                        "external_conky": []})
    s = tf.load_settings()
    tf.save_profile(s, "Gaming")
    s["palette"] = palette(tf, "Nord")
    tf.save_profile(s, "Chill")
    assert [x["name"] for x in s["profiles"]] == ["Gaming", "Chill"]
    assert s["profiles"][0]["panels"] == ["p1"]
    assert tf.next_profile_name(s) == "Gaming"          # current is Chill → wraps around
    s["current_profile"] = "Gaming"
    assert tf.next_profile_name(s) == "Chill"
    tf.save_profile(s, "Gaming")                          # updating keeps one entry
    assert len(s["profiles"]) == 2


def test_switch_profile_applies_palette_and_running_set(tf, home, monkeypatch):
    calls = {}
    monkeypatch.setattr(tf, "apply_all", lambda s, log: calls.setdefault("palette", s["palette"]["name"]))
    monkeypatch.setattr(tf, "set_running", lambda s, prof: calls.setdefault("running", prof["widgets"]))
    monkeypatch.setattr(tf, "ensure_service", lambda: calls.setdefault("service", True))
    s = tf.load_settings()
    prof = {"name": "Chill", "palette": palette(tf, "Nord"), "wallpaper": "", "targets": {"kitty": False},
            "album": True, "widgets": ["abc"], "visualizers": [], "panels": [], "external_conky": []}
    s["profiles"] = [prof]
    tf.switch_profile(s, "Chill", lambda *_: None)
    assert calls == {"palette": "Nord", "running": ["abc"], "service": True}
    saved = tf.load_settings()
    assert saved["current_profile"] == "Chill" and saved["targets"]["kitty"] is False
    assert saved["album"]["enabled"] is True
    with pytest.raises(ValueError):
        tf.switch_profile(s, "Nope", lambda *_: None)


def test_settings_from_21_upgrade_cleanly(tf, home):
    tf.CFG_DIR.mkdir(parents=True, exist_ok=True)
    tf.SETTINGS_FILE.write_text(json.dumps({"palette": palette(tf), "visualizers_palette": palette(tf),
                                            "visualizers": [{"id": "a", "style": "radial"}]}))
    s = tf.load_settings()
    assert "visualizers_palette" not in s
    assert s["visualizers"][0]["wrap"] == "" and s["visualizers"][0]["glow"] is False
    assert s["panels"] == [] and s["album"]["enabled"] is False and s["profiles"] == []


# ── community themes ───────────────────────────────────────────────

def test_community_theme_index_is_valid_and_current(tf):
    r = subprocess.run([sys.executable, str(ROOT / "tools/build_theme_index.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    index = json.loads((ROOT / "themes/index.json").read_text())
    assert len(index["themes"]) >= 5
    for t in index["themes"]:
        assert tf.valid_palette(t["palette"]), t["name"]
