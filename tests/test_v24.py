"""Tests for 2.4: calendar, countdown, drives, network and notes panels, customization, particles."""
import time

from PySide6.QtCore import QPointF, QRectF


def test_notes_parsing_and_toggling(tf, home):
    panel = tf.panel_template("notes")
    path = tf.ensure_notes_file(panel)
    assert path == home / "Notes" / "desktop.md" and path.read_text() == tf.SAMPLE_NOTES
    kinds = [k for k, _, _ in tf.parse_notes(tf.SAMPLE_NOTES)]
    assert kinds == ["h", "done", "todo", "todo", "gap", "h", "bullet", "bullet"]
    idx = next(i for k, _, i in tf.parse_notes(tf.SAMPLE_NOTES) if k == "todo")
    assert tf.toggle_note(panel, idx)
    assert path.read_text().split("\n")[idx] == "- [x] Daily Trove run"
    assert tf.toggle_note(panel, idx) and "- [ ] Daily Trove run" in path.read_text()
    assert not tf.toggle_note(panel, 0)                   # a heading isn't a checkbox
    lay, _ = tf.panel_layout(panel)
    row = next(r for r in lay["note_rows"] if r[2] == idx)
    assert tf.panel_hit(panel, 0, row[3].center()) == ("check", idx)


def test_notes_without_a_file(tf, home):
    panel = tf.panel_template("notes")
    lines = tf.notes_lines(panel)
    assert len(lines) == 1 and "right-click" in lines[0][1].lower()


def test_calendar_grid_and_hits(tf):
    for y, m in ((2026, 2), (2026, 10), (2027, 1)):
        weeks = tf.calendar_weeks(y, m)
        assert len(weeks) == 6 and all(len(w) == 7 for w in weeks)
        assert weeks[0][0].weekday() == 6                  # Sunday first by default
    assert tf.calendar_weeks(2026, 10, "monday")[0][0].weekday() == 0
    assert tf.shift_month(2026, 12, 1) == (2027, 1) and tf.shift_month(2026, 1, -1) == (2025, 12)
    cal = tf.panel_template("calendar")
    lay, _ = tf.panel_layout(cal)
    assert len(lay["cal_cells"]) == 42
    assert tf.panel_hit(cal, 0, lay["cal_next"].center()) == ("month", 1)
    assert tf.panel_hit(cal, 0, lay["cal_prev"].center()) == ("month", -1)


def test_countdown_math(tf):
    assert tf.countdown_parts(90061) == {"days": 1, "hours": 1, "minutes": 1, "seconds": 1}
    assert tf.countdown_parts(-5) == {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}
    t = tf.parse_target("2027-01-01 00:00")
    assert time.localtime(t).tm_year == 2027 and tf.parse_target("not a date") is None
    assert tf.parse_target("2027-03-04") is not None


def test_drives_and_byte_formatting(tf):
    drives = tf.drives_info()
    assert all(0 <= d["used"] <= d["total"] for d in drives)
    assert len({d["mount"] for d in drives}) == len(drives)
    if drives:
        assert tf.drives_info(drives[0]["mount"])[0]["mount"] == drives[0]["mount"]
    assert tf.fmt_bytes(1.82e12) == "1.8 TB" and tf.fmt_bytes(273e9) == "273 GB" and tf.fmt_bytes(5e6) == "5.0 MB"


def test_per_thread_cpu(tf, monkeypatch):
    monkeypatch.setattr(tf, "_gpu_reading", lambda: (None, None))
    _, state = tf.collect_stats()
    stats, _ = tf.collect_stats(state)
    fracs, label = stats["cores"]
    assert len(fracs) == len(tf._core_times()) and label.endswith("threads")
    assert all(0.0 <= f <= 1.0 for f in fracs)


def test_highlight_color_and_fonts(tf):
    p = tf.PRESETS["Nord"]
    assert tf.panel_palette(p, {"highlight": "accent"}) is p
    swapped = tf.panel_palette(p, {"highlight": "accent2"})
    assert swapped["accent"] == p["accent2"] and swapped["accent2"] == p["accent"]
    assert tf.panel_palette(p, {"highlight": "red"})["accent"] == p["ansi"][1]
    tf._FONT.update(family="DejaVu Sans", scale=1.5)
    try:
        assert tf._font(10).pointSizeF() == 15 and tf._font(10).family().startswith("DejaVu")
    finally:
        tf._FONT.update(family="", scale=1.0)


def test_all_customizations_paint(tf):
    from PySide6.QtGui import QColor, QImage, QPainter
    pal = tf.PRESETS["Dracula"]
    hist = [(1e6 * (k % 7), 2e5) for k in range(62)]
    state = {"t": 2.0, "now": time.time(), "appear": 0.5, "fade": 0.4, "moving": True, "glow": 0.3,
             "drives": tf.SAMPLE_DRIVES, "net_hist": hist, "net_max": 8e6, "net_phase": 0.3,
             "month_offset": 1, "month_anim": 0.5, "check_anim": {1: 0.5}, "hover": ("month", 1)}
    for kind in ("calendar", "countdown", "drives", "network", "notes"):
        for bg in ("solid", "gradient", "frosted", "outline"):
            for entrance in ("fade", "slide", "pop"):
                panel = dict(tf.panel_template(kind), background=bg, entrance=entrance, shadow=True, pulse=True,
                             highlight="cyan", font_scale=120)
                n = len(tf.SAMPLE_DRIVES) if kind == "drives" else 0
                lay, full = tf.panel_layout(panel, n)
                img = QImage(int(full.width()) + 40, int(full.height()) + 40, QImage.Format_ARGB32)
                img.fill(QColor("#000000"))
                qp = QPainter(img)
                tf.paint_panel(qp, QPointF(20, 20), panel, pal, state)
                qp.end()
    assert tf._FONT == {"family": "", "scale": 1.0}       # restored after painting


def test_particles_and_flowing_colors(tf):
    sim = tf.ParticleSim()
    vals = [0.0] * 32
    sim.update(vals, 0.016, 640, 320)
    sim.update([0.9] * 32, 0.016, 640, 320)               # a sudden rise throws sparks
    assert len(sim.parts) > 32
    for _ in range(200):
        sim.update(vals, 0.05, 640, 320)
    assert sim.parts == []                                # everything falls back down
    cols = ["#000000", "#ffffff"]
    assert tf.flow_colors(cols, 0.0)[0] == "#000000"
    assert tf.flow_colors(cols, 0.5)[0] != "#000000" and len(tf.flow_colors(cols, 0.3)) == 6
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(400, 300, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    qp = QPainter(img)
    for style in ("particles", "dots"):
        v = dict(tf.vis_template(style), flow=True, glow=True, peaks=True)
        sim.update([0.9] * tf.vis_bar_count(v), 0.016, 400, 300)
        vals = tf.fake_spectrum(tf.vis_bar_count(v), 1.0, v["stereo"])
        tf.paint_visualizer(qp, QRectF(0, 0, 400, 300), vals, v, tf.PRESETS["Nord"],
                            tf.update_peaks([], vals, 0), 1.5, sim)
    qp.end()


def test_old_panels_get_customization_defaults(tf):
    p = tf.normalize_panel({"id": "x", "kind": "clock"})
    assert (p["background"], p["entrance"], p["highlight"], p["anim_speed"]) == ("solid", "fade", "accent", 100)
    assert tf.normalize_panel({"id": "y", "kind": "bogus"})["kind"] == "launcher"
