"""Tests for ThemeForge's config generators. No real desktop or Qt display needed."""
import copy


def palette(tf):
    return copy.deepcopy(tf.PRESETS["Tokyo Night"])


def test_presets_are_valid(tf):
    for name, p in tf.PRESETS.items():
        assert tf.valid_palette(p), name
        assert len(p["ansi"]) == 16


def test_kitty_include_is_added_once_and_kept_last(tf, home):
    conf = home / ".config/kitty/kitty.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("font_size 12\ninclude current-theme.conf\n")
    for _ in range(3):
        tf.apply_kitty(palette(tf), {}, lambda *_: None)
    text = conf.read_text()
    assert text.count("include themeforge.conf") == 1
    assert text.strip().endswith("include themeforge.conf")
    assert "font_size 12" in text
    assert "background #1a1b26" in (home / ".config/kitty/themeforge.conf").read_text()


def test_cava_color_section_replaced_and_rest_kept(tf, home):
    cfg = home / ".config/cava/config"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("[general]\nbars = 0\n\n[color]\nforeground = 'cyan'\n\n[smoothing]\nnoise_reduction = 77\n")
    tf.apply_cava(palette(tf), {}, lambda *_: None)
    tf.apply_cava(palette(tf), {}, lambda *_: None)
    text = cfg.read_text()
    assert text.lower().count("[color]") == 1
    assert "noise_reduction = 77" in text and "bars = 0" in text
    assert "'cyan'" not in text and "gradient = 1" in text


def test_backup_and_restore_round_trip(tf, home):
    conf = home / ".config/kitty/kitty.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("original\n")
    tf.apply_kitty(palette(tf), {}, lambda *_: None)
    tf.apply_cava(palette(tf), {}, lambda *_: None)       # cava config didn't exist before
    tf.restore_originals({}, lambda *_: None)
    assert conf.read_text() == "original\n"
    assert not (home / ".config/cava/config").exists()


def test_ini_set_edits_only_the_target_key(tf, home):
    f = home / "profile"
    f.write_text("[Appearance]\nColorScheme=Breeze\nFont=Hack,10\n\n[General]\nName=Mine\n")
    tf.ini_set(f, "Appearance", "ColorScheme", "ThemeForge")
    tf.ini_set(f, "New", "Key", "1")
    assert tf.ini_get(f, "Appearance", "ColorScheme") == "ThemeForge"
    assert tf.ini_get(f, "Appearance", "Font") == "Hack,10"
    assert tf.ini_get(f, "General", "Name") == "Mine"
    assert tf.ini_get(f, "New", "Key") == "1"


def test_conky_recolor_only_touches_known_keys(tf, home):
    f = home / "conky.conf"
    f.write_text("conky.config = {\n  default_color = 'ffffff',\n  color1 = '#ff8800',\n  color10 = 'abcdef',\n}\n")
    assert tf.recolor_conky(f, palette(tf)) == 2
    text = f.read_text()
    assert "color10 = 'abcdef'" in text and "ff8800" not in text


def test_every_widget_block_generates(tf):
    p = palette(tf)
    for btype in tf.BLOCK_TYPES:
        w = tf.widget_template("blank")
        w["blocks"] = [tf.new_block(btype)]
        cfg = tf.conky_config(w, p)
        assert "conky.text = [[" in cfg
        assert tf.preview_rows(w["blocks"][0], w, p) is not None


def test_widget_text_is_escaped(tf):
    w = tf.widget_template("blank")
    w["blocks"] = [tf.new_block("text", text="#1 ]] fan")]
    line = tf.conky_lines(w["blocks"][0], w, palette(tf))[0]
    assert "\\#1" in line and "]]" not in line


def test_cava_raw_config_and_frame_parsing(tf):
    v = tf.vis_template("radial")
    v["bars"] = 33                            # stereo needs an even bar count
    cfg = tf.cava_raw_config(v)
    assert "bars = 34" in cfg and "method = raw" in cfg and "channels = stereo" in cfg
    assert tf.parse_cava_frame("0;500;1000;\n") == [0.0, 0.5, 1.0]
    assert tf.parse_cava_frame("garbage") is None


def test_visualizer_geometry(tf):
    from PySide6.QtCore import QRectF
    screen = QRectF(0, 0, 1920, 1080)
    v = tf.vis_template("bottom")              # full width, bottom
    assert tf.vis_geometry(v, screen).getRect() == (0, 1080 - 150, 1920, 150)
    v = tf.vis_template("radial")              # middle right, 120px in from the edge
    r = tf.vis_geometry(v, screen)
    assert r.right() == 1920 - 120 and r.center().y() == 540


def test_version_comparison(tf):
    pv = tf.parse_version
    assert pv("v2.10.0") > pv("2.9.9")
    assert pv("2.1") == pv("2.1.0")
    assert pv("3") > pv(tf.VERSION)


def test_settings_survive_old_or_partial_files(tf, home):
    tf.CFG_DIR.mkdir(parents=True, exist_ok=True)
    tf.SETTINGS_FILE.write_text('{"palette": {"broken": true}, "targets": {"kitty": false}}')
    s = tf.load_settings()
    assert tf.valid_palette(s["palette"])
    assert s["targets"]["kitty"] is False and "visualizers" in s["targets"]
    assert s["visualizers"]
