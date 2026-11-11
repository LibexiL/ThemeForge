"""Tests for snapping panels into line while moving them (2.8)."""
from PySide6.QtCore import QPointF, QRectF

SCREEN = QRectF(0, 0, 1920, 1040)


def test_lines_up_edges_and_centres(tf):
    other = QRectF(100, 100, 300, 200)
    dx, dy, guides = tf.snap_move(QRectF(106, 600, 200, 100), [other], SCREEN)
    assert (dx, dy) == (-6, 0)                                     # left edges line up
    assert guides == [("v", 100, 100, 700)]                        # guide spans both panels
    dx, _, _ = tf.snap_move(QRectF(155, 600, 200, 100), [other], SCREEN)
    assert dx == -5                                                # centres: 255 → 250
    dx, _, _ = tf.snap_move(QRectF(300, 600, 200, 100), [other], SCREEN)
    assert dx == 0                                                 # nothing within 10 px


def test_sits_beside_with_an_even_gap_or_touching(tf):
    other = QRectF(100, 100, 300, 200)
    dx, dy, guides = tf.snap_move(QRectF(420, 130, 200, 100), [other], SCREEN)
    assert dx == -4 and dy == 0 and guides[0][0] == "v"            # 416 = right edge + 16 px gap
    dx, _, _ = tf.snap_move(QRectF(403, 130, 200, 100), [other], SCREEN)
    assert dx == -3                                                # touching
    _, dy, _ = tf.snap_move(QRectF(120, 322, 200, 100), [other], SCREEN)
    assert dy == -6                                                # below it, 16 px gap
    dx, _, _ = tf.snap_move(QRectF(420, 800, 200, 100), [other], SCREEN)
    assert dx == 0                                                 # far below: no "beside" snap


def test_screen_edges_and_centre(tf):
    dx, dy, guides = tf.snap_move(QRectF(1714, 7, 200, 100), [], SCREEN)
    assert (dx, dy) == (6, -7)
    assert ("v", 1920, 0, 1040) in guides and ("h", 0, 0, 1920) in guides
    dx, _, _ = tf.snap_move(QRectF(855, 400, 200, 100), [], SCREEN)
    assert dx == 5                                                 # centre of the screen


def test_closest_line_wins(tf):
    a, b = QRectF(100, 100, 300, 200), QRectF(103, 400, 300, 200)
    dx, _, guides = tf.snap_move(QRectF(105, 700, 200, 80), [a, b], SCREEN)
    assert dx == -2 and guides[0][1] == 103


def test_only_running_panels_are_targets(tf, home, monkeypatch):
    s = tf.load_settings()
    s["panels"] = [tf.panel_template("clock"), tf.panel_template("lyrics"), tf.panel_template("notes")]
    tf.save_settings(s)
    a, b, c = (x["id"] for x in s["panels"])
    monkeypatch.setattr(tf, "_process_argvs", lambda: [(1, ["themeforge.py", "--panel", b]),
                                                       (2, ["themeforge.py", "--panel", a])])
    rects = tf.other_panel_rects(a)
    assert len(rects) == 1 and rects[0].width() == s["panels"][1]["width"]


def test_dragging_a_panel_snaps_and_saves_exactly(tf, home, monkeypatch, qapp):
    s = tf.load_settings()
    panel = dict(tf.panel_template("clock"), alignment="top_left", gap_x=40, gap_y=40, opacity=60)
    s["panels"] = [panel]
    tf.save_settings(s)
    w = tf.PanelWindow(panel["id"])
    try:
        w.show()
        qapp.processEvents()
        m = tf.GLOW_MARGIN
        geo = QRectF(w.screen().availableGeometry())
        other = QRectF(geo.left() + 301, geo.top() + 207, 200, 120)
        monkeypatch.setattr(tf, "other_panel_rects", lambda skip: [other])
        w.start_move()
        w.drag_offset = QPointF(0, 0)
        w.drag_to(QPointF(other.left() + 3 - m, other.bottom() + 20 - m))     # just below it, almost lined up
        body = QRectF(w.geometry()).adjusted(m, m, -m, -m)
        assert body.left() == other.left() and body.top() == other.bottom() + tf.SNAP_GAP
        assert w.snapped and w.guides is not None and w.guides.guides
        w.end_move()
        saved = tf.load_settings()["panels"][0]
        assert (saved["gap_x"], saved["gap_y"]) == (301, 207 + 120 + 16)     # not rounded to the 4 px grid
        assert w.guides is None and not w.moving
    finally:
        w.close()
