"""Tests for following Wallpaper Engine (2.6)."""
import json
import time

from PySide6.QtGui import QColor, QImage

MON1 = "//?/DISPLAY#GSM5A90#5&1fc1427d&6&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"
MON2 = "//?/DISPLAY#DELA0B1#5&2&UID4353#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"


def gif(path, color):
    """A 1x1 GIF in one color (Qt reads GIFs but can't write them)."""
    rgb = bytes(QColor(color).getRgb()[:3])
    path.write_bytes(b"GIF89a\x01\x00\x01\x00\x80\x00\x00" + rgb + b"\x00\x00\x00"
                     + b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00;")
    return path


def image(path, color, size=(64, 64)):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gif":
        return gif(path, color)
    img = QImage(*size, QImage.Format_RGB32)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path))
    return path


def workshop(lib, wid, kind, title, file, preview, color):
    d = lib / "steamapps" / "workshop" / "content" / "431960" / wid
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps({"title": title, "type": kind, "file": file, "preview": preview}),
                                    encoding="utf-8")
    if preview:
        image(d / preview, color)
    if file.endswith(".jpg"):
        image(d / file, color, (320, 180))
    else:
        (d / file).write_bytes(b"x")
    return (d / file).as_posix()


def install(tf, home, monkeypatch, selected=None, user="BexPC", nested=True):
    """A Steam install with the library holding Wallpaper Engine in a second folder."""
    steam, lib2 = home / "Steam", home / "Games" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (str(steam).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")), encoding="utf-8")
    scene = workshop(lib2, "1552273169", "scene", "Neon City", "scene.pkg", "preview.gif", "#7a1fd1")
    video = workshop(lib2, "883645814", "video", "Rain Window", "rain.mp4", "preview.jpg", "#1f9e4a")
    picture = workshop(lib2, "902735100", "", "Sunset", "sunset.jpg", "", "#e06a12")
    sel = selected or {MON1: {"file": scene, "playlist": {"items": [scene, video]}}, MON2: {"file": video}}
    wc = {"wallpaperconfig": {"selectedwallpapers": sel}}
    cfg = {user: ({"general": wc} if nested else wc), "version": 2}
    path = lib2 / "steamapps" / "common" / "wallpaper_engine" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    monkeypatch.setattr(tf, "IS_WINDOWS", True)
    monkeypatch.setattr(tf, "win_reg_get", lambda key, name: ("sz", str(steam)) if name == "SteamPath" else None)
    return path, {"scene": scene, "video": video, "picture": picture}


def test_finds_config_through_steam_libraries(tf, home, monkeypatch):
    path, _ = install(tf, home, monkeypatch)
    assert tf.find_wpe_config() == path
    custom = home / "elsewhere" / "config.json"
    custom.parent.mkdir()
    custom.write_text("{}", encoding="utf-8")
    assert tf.find_wpe_config({"wpe": {"config": str(custom)}}) == custom


def test_reads_selected_wallpapers_old_and_new_layouts(tf, home, monkeypatch):
    path, files = install(tf, home, monkeypatch, nested=False)
    sel = tf.wpe_selected(path)
    assert list(sel) == [MON1, MON2] and sel[MON1] == files["scene"]
    assert tf.wpe_pick(sel) == (MON1, files["scene"])
    assert tf.wpe_pick(sel, MON2) == (MON2, files["video"])
    assert tf.wpe_pick(sel, "gone") == (MON1, files["scene"])
    assert tf.wpe_pick({}) == (None, None)
    assert tf.wpe_monitor_label(MON1, 0) == "Monitor 1 (GSM5A90)" and tf.wpe_monitor_label("Monitor0", 1) == "Monitor 2"


def test_wallpaper_images(tf, home, monkeypatch):
    _, files = install(tf, home, monkeypatch)
    scene = tf.wpe_wallpaper_info(files["scene"])
    assert scene["title"] == "Neon City" and scene["type"] == "scene" and scene["image"].name == "preview.gif"
    assert tf.wpe_wallpaper_info(files["video"])["image"].name == "preview.jpg"
    assert tf.wpe_wallpaper_info(files["picture"])["image"].name == "sunset.jpg"       # full-size image
    assert tf.wpe_wallpaper_info(str(home / "missing" / "scene.pkg"))["image"] is None
    gif_img = QImage(str(scene["image"]))
    assert not gif_img.isNull() and gif_img.pixelColor(0, 0).name() == "#7a1fd1"


def test_kde_plugin_source(tf, home, monkeypatch):
    rc = home / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
    rc.parent.mkdir(parents=True, exist_ok=True)
    rc.write_text("[Containments][1][Wallpaper][com.github.catsout.wallpaperEngineKde][General]\n"
                  "WallpaperSource=file:///home/me/.steam/steam/steamapps/workshop/content/431960/42/scene%20one.pkg\n",
                  encoding="utf-8")
    monkeypatch.setattr(tf, "KDE_APPLETSRC", rc)
    monkeypatch.setattr(tf, "IS_WINDOWS", False)
    assert tf.find_wpe_config() == rc
    assert tf.wpe_selected(rc) == {"Screen0": "/home/me/.steam/steam/steamapps/workshop/content/431960/42/scene one.pkg"}


def test_watcher_applies_palette_and_follows_changes(tf, home, monkeypatch, qapp):
    path, files = install(tf, home, monkeypatch)
    applied = []
    monkeypatch.setattr(tf, "apply_all", lambda s, log: applied.append((s["palette"]["name"],
                                                                      s["targets"].get("wallpaper"))))
    s = tf.load_settings()
    s["wpe"]["enabled"] = True
    tf.save_settings(s)
    w = tf.WallpaperEngineWatcher()

    def settle(cond):
        end = time.monotonic() + 10
        while time.monotonic() < end and not cond():
            qapp.processEvents()
            time.sleep(0.02)
        return cond()
    w.configure(tf.load_settings())
    assert settle(lambda: applied and not w.busy)
    assert applied == [("Wallpaper Engine: Neon City", False)]          # never touches the wallpaper itself
    s = tf.load_settings()
    assert s["palette"]["name"] == "Wallpaper Engine: Neon City" and s["wpe"]["last"] == files["scene"]
    st = json.loads(tf.WPE_STATUS_FILE.read_text(encoding="utf-8"))
    assert st["state"] == "on" and st["title"] == "Neon City" and tf.valid_palette(st["palette"])

    w.configure(tf.load_settings())                                       # same wallpaper: nothing to do
    w.check()
    assert settle(lambda: not w.busy) and len(applied) == 1

    cfg = json.loads(path.read_text(encoding="utf-8"))                    # pick the picture wallpaper
    cfg["BexPC"]["general"]["wallpaperconfig"]["selectedwallpapers"][MON1]["file"] = files["picture"]
    time.sleep(0.05)
    path.write_text(json.dumps(cfg), encoding="utf-8")
    w.check()
    assert settle(lambda: len(applied) == 2 and not w.busy)
    assert tf.load_settings()["palette"]["name"] == "Wallpaper Engine: Sunset"

    s = tf.load_settings()                                                # follow the second monitor instead
    s["wpe"].update(monitor=MON2, last="")
    tf.save_settings(s)
    w.configure(s)
    assert settle(lambda: len(applied) == 3 and not w.busy)
    assert applied[-1][0] == "Wallpaper Engine: Rain Window"
    w.configure({"wpe": dict(tf.WPE_DEFAULTS)})
    assert not w.timer.isActive()


def test_watcher_waits_while_album_art_is_showing(tf, home, monkeypatch, qapp):
    install(tf, home, monkeypatch)
    applied = []
    monkeypatch.setattr(tf, "apply_all", lambda s, log: applied.append(1))
    s = tf.load_settings()
    s["wpe"]["enabled"] = True
    s["album"]["enabled"] = True
    tf.save_settings(s)
    tf.ALBUM_STATUS_FILE.write_text(json.dumps({"state": "on"}), encoding="utf-8")
    w = tf.WallpaperEngineWatcher()
    w.configure(tf.load_settings())
    end = time.monotonic() + 10
    while time.monotonic() < end and (w.busy or tf.load_settings()["wpe"]["last"] == ""):
        qapp.processEvents()
        time.sleep(0.02)
    assert applied == [] and tf.load_settings()["palette"]["name"] == "Wallpaper Engine: Neon City"


def test_missing_install_and_settings(tf, home, monkeypatch):
    monkeypatch.setattr(tf, "IS_WINDOWS", True)
    monkeypatch.setattr(tf, "win_reg_get", lambda key, name: None)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert tf.find_wpe_config() is None
    s = tf.load_settings()
    assert s["wpe"] == tf.WPE_DEFAULTS and not tf.service_wanted(s)
    s["wpe"]["enabled"] = True
    assert tf.service_wanted(s)


def test_print_survives_a_non_utf8_log(tf, monkeypatch):
    """Windows gives a process whose output goes to a file the ANSI code page (cp1252)."""
    import io
    import sys
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", None)
    tf.fix_stdio()
    print("✓ Windows Terminal ✗ → ♪")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").startswith("✓ Windows Terminal ✗ → ♪")
    assert sys.stderr is not None
    sys.stderr.close()
