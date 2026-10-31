"""Tests for 2.3: animation helpers and the clock, system and weather panels."""
import sys
import copy

from PySide6.QtCore import QPointF

SAMPLE = {"current_condition": [{"temp_C": "18", "temp_F": "64", "FeelsLikeC": "17", "FeelsLikeF": "62",
                                 "humidity": "58", "weatherCode": "296", "weatherDesc": [{"value": "Light rain "}],
                                 "windspeedKmph": "11", "windspeedMiles": "7"}],
          "nearest_area": [{"areaName": [{"value": "Raleigh"}]}],
          "weather": [{"date": "2026-10-18", "maxtempC": "20", "maxtempF": "68", "mintempC": "11", "mintempF": "51",
                       "astronomy": [{"sunrise": "07:21 AM", "sunset": "06:35 PM"}],
                       "hourly": [{"weatherCode": "116"}] * 8},
                      {"date": "2026-10-19", "maxtempC": "16", "maxtempF": "61", "mintempC": "9", "mintempF": "49",
                       "hourly": [{"weatherCode": "389"}] * 8}]}


def test_parse_weather_both_unit_systems(tf):
    us = tf.parse_weather(SAMPLE, "us")
    assert (us["temp"], us["unit"], us["wind"], us["area"]) == (64, "F", "7 mph", "Raleigh")
    assert us["desc"] == "Light rain" and us["code"] == 296
    assert [d["name"] for d in us["days"]] == ["Today", "Mon"]
    assert us["days"][1] == {"name": "Mon", "code": 389, "hi": 61, "lo": 49}
    metric = tf.parse_weather(SAMPLE, "metric")
    assert (metric["temp"], metric["unit"], metric["wind"]) == (18, "C", "11 km/h")


def test_weather_kinds_and_sample_conversion(tf):
    assert tf.weather_kind(113) == "clear" and tf.weather_kind(296) == "rain"
    assert tf.weather_kind(389) == "thunder" and tf.weather_kind(338) == "snow"
    assert tf.weather_kind(12345) == "cloudy"
    m = tf.sample_weather("metric")
    assert m["unit"] == "C" and m["temp"] == round((64 - 32) * 5 / 9)
    assert tf.weather_url("New York") == "https://wttr.in/New+York?format=j1"
    assert tf._clock_minutes("06:35 PM") == 18 * 60 + 35 and tf._clock_minutes("12:05 AM") == 5


def test_collect_stats_reads_this_machine(tf, monkeypatch):
    monkeypatch.setattr(tf, "_gpu_reading", lambda: (37, 58.0))
    first, state = tf.collect_stats()
    second, _ = tf.collect_stats(state)
    for key in ("cpu", "ram", "disk", "gpu", "gputemp", "cputemp"):
        frac, label = second[key]
        assert 0.0 <= frac <= 1.0 and isinstance(label, str)
    assert second["gpu"] == (0.37, "37%") and second["gputemp"][1] == "58°C"
    assert len(second["net"]) == 2
    assert tf.fmt_rate(1_500_000) == "1.5 MB/s" and tf.fmt_rate(512) == "512 B/s"


def test_lerp_palette_endpoints_and_gradient_lengths(tf):
    a, b = copy.deepcopy(tf.PRESETS["Nord"]), copy.deepcopy(tf.PRESETS["Dracula"])
    b["gradient"] = b["gradient"][:2]
    assert tf.lerp_palette(a, b, 1.0) == b
    start = tf.lerp_palette(a, b, 0.0)
    assert start["background"] == a["background"] and start["ansi"] == a["ansi"]
    mid = tf.lerp_palette(a, b, 0.5)
    assert len(mid["gradient"]) == max(len(a["gradient"]), 2) and tf.valid_palette(mid)


def test_peak_caps_hold_then_fall(tf):
    peaks = tf.update_peaks([], [1.0, 0.2], 0.0)
    peaks = tf.update_peaks(peaks, [0.0, 0.5], 0.2)        # held
    assert peaks[0][0] == 1.0 and peaks[1][0] == 0.5
    for _ in range(5):
        peaks = tf.update_peaks(peaks, [0.0, 0.0], 0.1)
    assert 0.0 < peaks[0][0] < 1.0                          # falling, not snapped down


def test_new_panel_layouts(tf):
    clock = tf.panel_template("clock")
    for style in ("ring", "digital", "analog"):
        clock["clock_style"] = style
        lay, full = tf.panel_layout(clock)
        assert full.width() >= clock["width"] and full.height() > clock["clock_size"]
    system = tf.panel_template("system")
    system["metrics"] = ["cpu", "ram", "gpu", "cputemp", "gputemp", "net"]
    lay, full = tf.panel_layout(system)
    assert len(lay["gauges"]) == (4 if sys.platform == "win32" else 5) and "net" in lay   # no CPU temp on Windows
    assert all(full.contains(r) for _, r in lay["gauges"])
    weather = tf.panel_template("weather")
    lay, full = tf.panel_layout(weather)
    assert len(lay["days"]) == 3
    assert tf.panel_hit(weather, 0, QPointF(30, 30)) == ("forecast", None)


def test_old_panels_gain_new_settings(tf):
    p = tf.normalize_panel({"id": "x", "kind": "nowplaying", "width": 380})
    assert p["art_style"] == "square" and p["animations"] is True and p["shimmer"] is False
    assert p["width"] == 380


def test_every_panel_kind_paints(tf):
    from PySide6.QtGui import QColor, QImage, QPainter
    import time
    pal = tf.PRESETS["Tokyo Night"]
    st = tf.fake_stats(1.0)
    state = {"t": 1.0, "now": time.time(), "stats": st, "shown": {m: v[0] for m, v in st.items() if m != "net"},
             "weather": tf.SAMPLE_WEATHER, "np": {"status": "Playing", "title": "x" * 80, "artist": "a",
                                                   "length": 100, "position": 10},
             "items": [{"name": "Trove", "path": "t", "type": "desktop", "icon": ""}], "icons": {},
             "hover": ("item", 0), "hover_amt": {0: 0.5}, "ripples": [(10, 10, 0.1)], "glow": 0.5, "appear": 0.5}
    for kind, _ in tf.PANEL_KINDS:
        for extra in ({}, {"shimmer": True, "glow": True, "art_style": "vinyl", "clock_style": "analog"}):
            panel = dict(tf.panel_template(kind), **extra)
            lay, full = tf.panel_layout(panel, 1)
            img = QImage(int(full.width()) + 40, int(full.height()) + 40, QImage.Format_ARGB32)
            img.fill(QColor("#000000"))
            qp = QPainter(img)
            tf.paint_panel(qp, QPointF(20, 20), panel, pal, state)
            qp.end()


def test_visualizer_orb_spin_and_peaks_paint(tf):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(300, 300, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    qp = QPainter(img)
    for style in ("orb", "radial", "bars", "mirror", "blocks", "frame"):
        v = dict(tf.vis_template("orb"), style=style, peaks=True, spin=30, glow=True)
        vals = tf.fake_spectrum(tf.vis_bar_count(v), 1.0, v["stereo"])
        tf.paint_visualizer(qp, QRectF(0, 0, 300, 300), vals, v, tf.PRESETS["Nord"],
                            tf.update_peaks([], vals, 0.0), 2.0)
    qp.end()
    assert tf._closed_spline([QPointF(0, 0), QPointF(10, 0), QPointF(5, 8)]).elementCount() > 3


def test_kwin_rule_merges_with_existing_rules_and_restores(tf, home):
    rules = home / ".config" / "kwinrulesrc"
    rules.parent.mkdir(parents=True)
    original = "[General]\ncount=1\nrules=abc-123\n\n[abc-123]\nDescription=My rule\nwmclass=steam\n"
    rules.write_text(original)
    assert tf.ensure_kwin_rule() is True
    assert tf.ensure_kwin_rule() is False                     # idempotent
    assert tf.ini_get(rules, "General", "rules") == "abc-123,themeforge-desktop-windows"
    assert tf.ini_get(rules, "General", "count") == "2"
    assert tf.ini_get(rules, "abc-123", "wmclass") == "steam"   # user's rule untouched
    for k, v in tf.KWIN_RULE.items():
        assert tf.ini_get(rules, "themeforge-desktop-windows", k) == v
    tf.restore_originals({}, lambda *_: None)
    assert rules.read_text() == original


def test_kwin_rule_created_from_scratch(tf, home, monkeypatch):
    monkeypatch.setattr(tf.shutil, "which", lambda n: "/usr/bin/" + n if n == "kwin_wayland" else None)
    assert tf.ensure_kwin_rule() is True
    rules = home / ".config" / "kwinrulesrc"
    assert tf.ini_get(rules, "General", "rules") == "themeforge-desktop-windows"
    assert tf.ini_get(rules, "themeforge-desktop-windows", "title") == "themeforge-"
