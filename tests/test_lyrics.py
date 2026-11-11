"""Tests for the lyrics panel (2.7). Lyrics here are made up."""
import json
import time

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter

LRC = """[ar: Test Band]
[offset:+500]
[00:01.00]First line of the song
[00:04.50][01:10.25]A line that comes back twice
[00:08.00]<00:08.00>Word <00:08.40>timed <00:08.90>line
[00:12.00]
[00:13.00]
[00:15.20]After the gap
[00:20.00]
"""


def test_parse_lrc(tf):
    lines = tf.parse_lrc(LRC)
    assert [ln[1] for ln in lines] == ["First line of the song", "A line that comes back twice", "Word timed line",
                                       "", "After the gap", "", "A line that comes back twice"]
    assert lines[0][0] == 0.5 and abs(lines[-1][0] - 69.75) < 1e-6        # offset moves lyrics earlier
    assert tf.parse_lrc("") == [] and tf.parse_lrc("no stamps here") == []


def test_clean_track_names(tf):
    c = tf.clean_track
    assert c('Test Band - "Song Name" (Official Music Video)', "TestBandVEVO") == ("Song Name", "Test Band")
    assert c("Song Name (feat. Someone Else)", "Test Band") == ("Song Name", "Test Band")
    assert c("Song Name [Lyric Video]", "Test Band - Topic") == ("Song Name", "Test Band")
    assert c("Song Name", "Test Band, Other Artist") == ("Song Name", "Test Band")
    assert c("Other Words - Song Name", "Test Band") == ("Other Words - Song Name", "Test Band")
    assert c("Test Band - Song Name", "") == ("Song Name", "Test Band")
    assert c("Song Name (Remastered 2011)", "Band") == ("Song Name (Remastered 2011)", "Band")


def record(**kw):
    base = {"id": 1, "trackName": "Song Name", "artistName": "Test Band", "albumName": "LP", "duration": 200,
            "instrumental": False, "plainLyrics": "One\nTwo", "syncedLyrics": "[00:01.00]One\n[00:02.00]Two"}
    base.update(kw)
    return base


def test_fetch_order_and_cache(tf, home):
    calls = []

    def http(path, params):
        calls.append((path, dict(params)))
        if path == "/api/get":
            return None
        return [record(id=2, duration=300), record(id=3, syncedLyrics=None, duration=201), record(id=4, duration=203)]
    res = tf.fetch_lyrics('Test Band - "Song Name" (Official Video)', "TestBandVEVO", "LP", 201.6, http=http)
    assert res["state"] == "synced" and res["lines"] == [[1.0, "One"], [2.0, "Two"]]
    assert calls[0] == ("/api/get", {"track_name": "Song Name", "artist_name": "Test Band", "album_name": "LP",
                                     "duration": 202})
    assert calls[1][1].get("album_name") is None and calls[2][0] == "/api/search"
    n = len(calls)
    again = tf.fetch_lyrics("Song Name", "Test Band", http=http)              # cached, no network
    assert again["lines"] == res["lines"] and len(calls) == n


def test_not_found_is_cached_for_a_day(tf, home):
    calls = []

    def http(path, params):
        calls.append(path)
        return [] if path == "/api/search" else None
    assert tf.fetch_lyrics("Nothing", "Nobody", http=http)["state"] == "none"
    n = len(calls)
    tf.fetch_lyrics("Nothing", "Nobody", http=http)
    assert len(calls) == n
    f = tf.lyrics_cache_file("Nothing", "Nobody")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["time"] = time.time() - 2 * 86400
    f.write_text(json.dumps(data), encoding="utf-8")
    tf.fetch_lyrics("Nothing", "Nobody", http=http)
    assert len(calls) > n


def test_records_and_best_match(tf):
    assert tf.lyrics_from_record(record(syncedLyrics=None))["state"] == "plain"
    assert tf.lyrics_from_record(record(syncedLyrics=None, plainLyrics=None, instrumental=True))["state"] == "instrumental"
    assert tf.lyrics_from_record(None)["state"] == "none"
    recs = [record(id=1, duration=260), record(id=2, duration=199, syncedLyrics=None), record(id=3, duration=215)]
    assert tf.best_lyrics_record(recs, 200)["id"] == 3                       # synced beats a closer plain one
    assert tf.best_lyrics_record([record(duration=400)], 200) is None        # a different recording
    assert tf.best_lyrics_record(recs, None)["id"] == 1


def test_scroll_and_wipe_timing(tf):
    lines = [[0.0, "one"], [4.0, "two two two"], [8.0, ""], [10.0, "four"]]
    assert tf.lyric_index(lines, -1) == -1 and tf.lyric_index(lines, 4.0) == 1 and tf.lyric_index(lines, 99) == 3
    assert tf.lyric_scroll(lines, 2.0) == 0.0
    assert tf.lyric_scroll(lines, 4.0) == 0.0 and tf.lyric_scroll(lines, 4.2) > 0.5
    assert tf.lyric_scroll(lines, 5.0) == 1.0
    assert tf.lyric_scroll([[None, "a"], [None, "b"], [None, "c"]], 50, synced=False, length=100) == 1.0
    assert tf.lyric_wipe(lines, 1, 4.0) == 0.0 and tf.lyric_wipe(lines, 1, 7.9) == 1.0
    assert 0 < tf.lyric_wipe(lines, 1, 4.5) < 1


def test_lyrics_panel_paints_every_state_and_reports_lines(tf):
    pal = tf.PRESETS["Dracula"]
    panel = tf.panel_template("lyrics")
    assert panel["kind"] == "lyrics" and ("lyrics", "Lyrics") in tf.PANEL_KINDS
    np = {"status": "Playing", "title": "Song", "artist": "Band", "length": 30.0, "position": 7.0}
    lay, full = tf.panel_layout(panel)
    for ly, n in ((None, None), ({"state": "loading"}, np), ({"state": "none"}, np), ({"state": "error"}, np),
                  ({"state": "instrumental"}, np), ({"state": "plain", "lines": [[None, "a"], [None, "b"]]}, np),
                  ({"state": "synced", "lines": tf.SAMPLE_LYRICS}, np)):
        for align, wipe, hl in (("left", True, "fg"), ("center", False, "accent")):
            hits = []
            img = QImage(int(full.width()) + 40, int(full.height()) + 40, QImage.Format_ARGB32)
            img.fill(QColor("#000000"))
            qp = QPainter(img)
            p2 = dict(panel, lyrics_align=align, lyrics_wipe=wipe, lyrics_hl=hl)
            tf.paint_panel(qp, QPointF(20, 20), p2, pal, {"t": 1.0, "np": n, "lyrics": ly, "lyric_hits": hits,
                                                          "hover": ("lyric", 3.2)})
            qp.end()
            if ly and ly["state"] == "synced":
                assert hits and all(lay["lyrics"].contains(r.center()) for r, _ in hits)
                assert {ts for _, ts in hits} <= {ts for ts, _ in tf.SAMPLE_LYRICS}


def test_now_playing_reports_album(tf):
    out = "Playing\tSong\tBand\t\t200000000\t1000000\tspotify\tThe Album\n"
    assert tf.parse_np(out)["album"] == "The Album"
    assert tf.parse_np("Playing\tSong\tBand\t\t200000000\t1000000\tspotify\n")["album"] == ""
