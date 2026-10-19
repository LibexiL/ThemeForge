#!/usr/bin/env python3
"""
ThemeForge - one palette for your whole Nobara / KDE Plasma desktop.

Themes kitty, cava, KDE Plasma (plus GTK apps that follow it), Konsole,
the wallpaper, your existing conky configs, desktop widgets you build
yourself (rendered with conky) and desktop music visualizers (audio from cava).

    python3 themeforge.py                   open the app
    python3 themeforge.py --apply           re-apply the saved theme (no GUI)
    python3 themeforge.py --start-widgets   start widgets/visualizers marked "start at login"
    python3 themeforge.py --update          check GitHub for a newer version and install it
    python3 themeforge.py --restore         put back the config files ThemeForge changed
    python3 themeforge.py --version
"""

import colorsys
import copy
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PySide6.QtCore import (QFileInfo, QFileSystemWatcher, QObject, QPointF, QProcess, QRectF, QSize,
                            Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QFontDatabase,
                           QFontMetricsF, QGradient, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileIconProvider, QSystemTrayIcon, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

VERSION = "2.2.0"
# GitHub "owner/repo" the auto-updater checks for new releases
GITHUB_REPO = "LibexiL/ThemeForge"
HOME = Path.home()
CFG_DIR = HOME / ".config" / "themeforge"
SETTINGS_FILE = CFG_DIR / "settings-v2.json"
THEMES_DIR = CFG_DIR / "themes"
WIDGETS_DIR = CFG_DIR / "widgets"
ORIG_DIR = CFG_DIR / "backups" / "originals"
AUTOSTART_FILE = HOME / ".config" / "autostart" / "themeforge-widgets.desktop"
SCRIPT = Path(__file__).resolve()


# ════════════════════════════════════════════════════════════════════
#  Color helpers
# ════════════════════════════════════════════════════════════════════

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def hex_to_rgb(h):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(clamp(c, 0, 255))) for c in rgb)


def to_hls(h):
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    return colorsys.rgb_to_hls(r, g, b)


def from_hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, clamp(l), clamp(s))
    return rgb_to_hex((r * 255, g * 255, b * 255))


def adjust(h, dl=0.0, ds=0.0):
    H, L, S = to_hls(h)
    return from_hls(H, L + dl, S + ds)


def mix(a, b, t):
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def luminance(h):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(bg, light="#ffffff", dark="#111111"):
    return light if contrast(bg, light) >= contrast(bg, dark) else dark


def is_dark(h):
    return luminance(h) < 0.2


def valid_hex(h):
    return isinstance(h, str) and bool(re.fullmatch(r"#?[0-9a-fA-F]{6}", h.strip()))


def norm_hex(h):
    return "#" + h.strip().lstrip("#").lower()


def hue_dist(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1 - d)


def dedupe(seq):
    out = []
    for c in seq:
        if c not in out:
            out.append(c)
    return out


# ════════════════════════════════════════════════════════════════════
#  Palettes
# ════════════════════════════════════════════════════════════════════

ROLES = [("background", "Background"), ("surface", "Surface"),
         ("foreground", "Text"), ("muted", "Muted text"),
         ("accent", "Accent"), ("accent2", "Second accent")]
ANSI_NAMES = ["Black", "Red", "Green", "Yellow", "Blue", "Magenta", "Cyan", "White"]


def default_gradient(p):
    a = p["ansi"]
    return dedupe([p["accent2"], p["accent"], a[5], a[1]])


def build_palette(name, bg, surface, fg, muted, accent, accent2,
                  red, green, yellow, blue, magenta, cyan, gradient=None):
    step = 0.07 if is_dark(bg) else -0.07
    normal = [surface, red, green, yellow, blue, magenta, cyan, mix(fg, muted, 0.3)]
    bright = [muted] + [adjust(c, step) for c in (red, green, yellow, blue, magenta, cyan)] + [fg]
    p = {"name": name, "background": bg, "surface": surface, "foreground": fg,
         "muted": muted, "accent": accent, "accent2": accent2, "ansi": normal + bright}
    p["gradient"] = list(gradient) if gradient else default_gradient(p)
    return p


#            bg         surface    text       muted      accent     accent2    red        green      yellow     blue       magenta    cyan
_PRESET_DATA = {
    "Catppuccin Mocha": ("#1e1e2e", "#313244", "#cdd6f4", "#6c7086", "#cba6f7", "#89b4fa", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5"),
    "Catppuccin Latte": ("#eff1f5", "#ccd0da", "#4c4f69", "#9ca0b0", "#8839ef", "#1e66f5", "#d20f39", "#40a02b", "#df8e1d", "#1e66f5", "#ea76cb", "#179299"),
    "Tokyo Night":      ("#1a1b26", "#24283b", "#c0caf5", "#565f89", "#7aa2f7", "#bb9af7", "#f7768e", "#9ece6a", "#e0af68", "#7aa2f7", "#bb9af7", "#7dcfff"),
    "Nord":             ("#2e3440", "#3b4252", "#eceff4", "#4c566a", "#88c0d0", "#81a1c1", "#bf616a", "#a3be8c", "#ebcb8b", "#81a1c1", "#b48ead", "#8fbcbb"),
    "Gruvbox Dark":     ("#282828", "#3c3836", "#ebdbb2", "#928374", "#fe8019", "#fabd2f", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c"),
    "Dracula":          ("#282a36", "#44475a", "#f8f8f2", "#6272a4", "#bd93f9", "#ff79c6", "#ff5555", "#50fa7b", "#f1fa8c", "#bd93f9", "#ff79c6", "#8be9fd"),
    "Rosé Pine":        ("#191724", "#26233a", "#e0def4", "#6e6a86", "#c4a7e7", "#ebbcba", "#eb6f92", "#31748f", "#f6c177", "#9ccfd8", "#c4a7e7", "#ebbcba"),
    "Everforest Dark":  ("#2d353b", "#3d484d", "#d3c6aa", "#859289", "#a7c080", "#83c092", "#e67e80", "#a7c080", "#dbbc7f", "#7fbbb3", "#d699b6", "#83c092"),
}
PRESETS = {name: build_palette(name, *vals) for name, vals in _PRESET_DATA.items()}


def valid_palette(p):
    try:
        if not all(valid_hex(p[k]) for k, _ in ROLES):
            return False
        if len(p["ansi"]) != 16 or not all(valid_hex(c) for c in p["ansi"]):
            return False
        return 1 <= len(p["gradient"]) <= 8 and all(valid_hex(c) for c in p["gradient"])
    except Exception:
        return False


def role_color(p, role):
    if role in ("background", "surface", "foreground", "muted", "accent", "accent2"):
        return p[role]
    idx = {"red": 1, "green": 2, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6}.get(role)
    return p["ansi"][idx] if idx else p["foreground"]


def best_text(c, p):
    """Whichever of the palette's background/foreground reads better on c."""
    return p["background"] if contrast(c, p["background"]) >= contrast(c, p["foreground"]) else p["foreground"]


def kde_view_color(p):
    bg = p["background"]
    return mix(bg, "#000000", 0.18) if is_dark(bg) else mix(bg, "#ffffff", 0.6)


# ── wallpaper → palette ─────────────────────────────────────────────

def extract_clusters(path, k=8, iters=10):
    img = QImage(str(path))
    if img.isNull():
        raise ValueError("Couldn't open that image.")
    img = img.scaled(64, 64, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
    px = []
    for y in range(img.height()):
        for x in range(img.width()):
            v = img.pixel(x, y)
            px.append(((v >> 16) & 255, (v >> 8) & 255, v & 255))

    def d2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2

    rnd = random.Random(7)
    cents = [px[rnd.randrange(len(px))]]
    while len(cents) < k:                       # k-means++ seeding
        dist = [min(d2(p, c) for c in cents) for p in px]
        total = sum(dist)
        if total == 0:
            break
        r, acc = rnd.random() * total, 0
        for p, d in zip(px, dist):
            acc += d
            if acc >= r:
                cents.append(p)
                break
    buckets = []
    for _ in range(iters):
        buckets = [[] for _ in cents]
        for p in px:
            buckets[min(range(len(cents)), key=lambda j: d2(p, cents[j]))].append(p)
        cents = [tuple(sum(c[i] for c in b) / len(b) for i in range(3)) if b else cents[j]
                 for j, b in enumerate(buckets)]
    res = [(rgb_to_hex(c), len(b) / len(px)) for c, b in zip(cents, buckets) if b]
    return sorted(res, key=lambda t: -t[1])


def palette_from_wallpaper(path, light=False):
    info = [(h, w, *to_hls(h)) for h, w in extract_clusters(path)]   # hex, weight, H, L, S
    base = max(info, key=lambda t: t[3]) if light else min(info, key=lambda t: t[3])
    bh, bs = base[2], min(base[4], 0.35)
    if light:
        bg, surface = from_hls(bh, 0.95, bs * 0.5), from_hls(bh, 0.87, bs * 0.5)
        fg, muted = from_hls(bh, 0.20, 0.20), from_hls(bh, 0.48, 0.10)
        acc_l, ansi_l = 0.42, 0.42
    else:
        bg, surface = from_hls(bh, 0.11, bs * 0.6), from_hls(bh, 0.18, bs * 0.6)
        fg, muted = from_hls(bh, 0.88, 0.18), from_hls(bh, 0.55, 0.12)
        acc_l, ansi_l = 0.70, 0.68

    vivid = sorted(info, key=lambda t: -(t[4] * (0.3 + t[1]) ** 0.5 * (1 - abs(t[3] - 0.5))))
    a = vivid[0]
    a_hue = a[2] if a[4] > 0.1 else 0.62          # greyscale wallpaper → default to blue
    accent = from_hls(a_hue, acc_l, max(a[4], 0.55))
    second = next((t for t in vivid[1:] if hue_dist(t[2], a_hue) > 0.08 and t[4] > 0.15), None)
    accent2 = (from_hls(second[2], acc_l, max(second[4], 0.5)) if second
               else from_hls(a_hue + 0.12, acc_l, max(a[4], 0.5)))

    avg_s = sum(t[4] * t[1] for t in info)
    sat = clamp(0.45 + avg_s * 0.5, 0.5, 0.8)

    def pick(target):
        cands = [t for t in info if t[4] > 0.25 and hue_dist(t[2], target) < 0.05]
        hue = max(cands, key=lambda t: t[1])[2] if cands else target
        return from_hls(hue, ansi_l, sat)

    red, yellow, green, cyan, blue, magenta = (pick(x) for x in (0.0, 0.12, 0.33, 0.5, 0.61, 0.83))
    return build_palette(f"From {Path(path).name}", bg, surface, fg, muted, accent, accent2,
                         red, green, yellow, blue, magenta, cyan)


# ════════════════════════════════════════════════════════════════════
#  Small file / process helpers
# ════════════════════════════════════════════════════════════════════

def backup(path):
    """Keep the very first version of any file we touch, so it can be restored."""
    path = Path(path)
    try:
        rel = path.relative_to(HOME)
    except ValueError:
        return
    orig = ORIG_DIR / rel
    absent = ORIG_DIR / (str(rel) + ".tf-absent")
    if orig.exists() or absent.exists():
        return
    orig.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, orig)
    else:
        absent.touch()


def ini_get(path, section, key):
    path = Path(path)
    if not path.exists():
        return None
    cur = None
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("["):
            cur = s
        elif cur == f"[{section}]" and "=" in s:
            k, v = s.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return None


def ini_set(path, section, key, value):
    """Set one key in a KDE-style INI file, leaving everything else alone."""
    path = Path(path)
    lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    header, out = f"[{section}]", []
    in_sec = found = done = False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if in_sec and not done:
                while out and not out[-1].strip():
                    out.pop()
                out += [f"{key}={value}", ""]
                done = True
            in_sec = s == header
            found = found or in_sec
        elif in_sec and not done and "=" in s and s.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            done = True
            continue
        out.append(line)
    if in_sec and not done:
        out.append(f"{key}={value}")
        done = True
    if not found:
        if out and out[-1].strip():
            out.append("")
        out += [header, f"{key}={value}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")


def run_cmd(cmd, log):
    if not shutil.which(cmd[0]):
        log(f"   ! {cmd[0]} isn't installed")
        return False
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        log(f"   ! {e}")
        return False
    out = (r.stdout + r.stderr).strip()
    if out:
        log("   " + out.splitlines()[-1])
    return r.returncode == 0


def signal_procs(name, sig):
    try:
        pids = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, timeout=5).stdout.split()
    except (FileNotFoundError, subprocess.SubprocessError):
        return 0
    n = 0
    for pid in pids:
        try:
            os.kill(int(pid), sig)
            n += 1
        except (ProcessLookupError, PermissionError, ValueError):
            pass
    return n


def conky_procs():
    try:
        out = subprocess.run(["pgrep", "-a", "conky"], capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    procs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and Path(parts[1]).name == "conky":
            procs.append((int(parts[0]), parts[2:]))
    return procs


def conky_pids(path, procs=None):
    procs = conky_procs() if procs is None else procs
    sp = str(path)
    return [pid for pid, args in procs if sp in args or f"--config={sp}" in args]


def start_conky(path):
    if not shutil.which("conky"):
        return False
    subprocess.Popen(["conky", "-c", str(path)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def stop_conky(path):
    for pid in conky_pids(path):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def detect_iface():
    try:
        out = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"\bdev\s+(\S+)", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════════════
#  Widgets (rendered by conky)
# ════════════════════════════════════════════════════════════════════

ALIGNMENTS = [("top_left", "Top left"), ("top_middle", "Top center"), ("top_right", "Top right"),
              ("middle_left", "Middle left"), ("middle_middle", "Center"), ("middle_right", "Middle right"),
              ("bottom_left", "Bottom left"), ("bottom_middle", "Bottom center"), ("bottom_right", "Bottom right")]
# conky color0..color9 → palette role
COLOR_SLOTS = ["foreground", "accent", "accent2", "muted", "red", "green", "yellow", "surface", "blue", "magenta"]
ROLE_NAMES = {"foreground": "Text", "accent": "Accent", "accent2": "Second accent", "muted": "Muted",
              "red": "Red", "green": "Green", "yellow": "Yellow", "surface": "Surface",
              "blue": "Blue", "magenta": "Magenta"}
TEXT_ALIGN = [("left", "Left"), ("center", "Center"), ("right", "Right")]


def F(key, kind, label, default, opts=None):
    return (key, kind, label, default, opts)


SIZE = (6, 160)
BLOCK_TYPES = {
    "clock":      ("Clock", [F("format", "text", "Time format", "%H:%M"), F("size", "int", "Size", 42, SIZE),
                             F("bold", "bool", "Bold", True), F("align", "align", "Align", "center"),
                             F("role", "role", "Color", "foreground")]),
    "date":       ("Date", [F("format", "text", "Date format", "%A, %d %B"), F("size", "int", "Size", 12, SIZE),
                            F("bold", "bool", "Bold", False), F("align", "align", "Align", "center"),
                            F("role", "role", "Color", "accent")]),
    "heading":    ("Heading", [F("text", "text", "Text", "SYSTEM"), F("size", "int", "Size", 11, SIZE),
                               F("bold", "bool", "Bold", True), F("align", "align", "Align", "left"),
                               F("role", "role", "Color", "accent")]),
    "text":       ("Text", [F("text", "text", "Text", "Hello there"), F("size", "int", "Size", 10, SIZE),
                            F("bold", "bool", "Bold", False), F("align", "align", "Align", "left"),
                            F("role", "role", "Color", "foreground")]),
    "cpu":        ("CPU", [F("label", "text", "Label", "CPU"),
                           F("style", "choice", "Style", "graph", ["graph", "bar", "text"]),
                           F("role", "role", "Color", "accent")]),
    "memory":     ("Memory", [F("label", "text", "Label", "RAM"),
                              F("style", "choice", "Style", "bar", ["bar", "graph", "text"]),
                              F("role", "role", "Color", "accent")]),
    "disk":       ("Disk", [F("label", "text", "Label", "Disk"), F("path", "text", "Mount point", "/"),
                            F("style", "choice", "Style", "bar", ["bar", "text"]),
                            F("role", "role", "Color", "accent")]),
    "network":    ("Network", [F("label_down", "text", "Download label", "Download"),
                               F("label_up", "text", "Upload label", "Upload"),
                               F("iface", "text", "Interface (blank = auto)", ""),
                               F("style", "choice", "Style", "graph", ["graph", "text"]),
                               F("role", "role", "Color", "accent2")]),
    "cputemp":    ("CPU temperature", [F("label", "text", "Label", "CPU temp"),
                                       F("units", "choice", "Units", "c", ["c", "f"]),
                                       F("role", "role", "Color", "foreground")]),
    "gpu":        ("GPU", [F("label", "text", "Label", "GPU"),
                           F("style", "choice", "Style", "bar", ["bar", "text"]),
                           F("temp", "bool", "Show temperature", True),
                           F("units", "choice", "Units", "c", ["c", "f"]),
                           F("role", "role", "Color", "accent")]),
    "calendar":   ("Calendar", [F("start", "choice", "Week starts on", "sunday", ["sunday", "monday"]),
                                F("size", "int", "Size", 10, SIZE), F("align", "align", "Align", "center"),
                                F("role", "role", "Today color", "accent")]),
    "nowplaying": ("Now playing", [F("size", "int", "Title size", 12, SIZE), F("align", "align", "Align", "left"),
                                   F("role", "role", "Color", "accent")]),
    "weather":    ("Weather", [F("location", "text", "Location (blank = auto)", ""),
                               F("units", "choice", "Units", "metric", ["metric", "us"]),
                               F("interval", "int", "Refresh (seconds)", 900, (60, 86400)),
                               F("size", "int", "Size", 11, SIZE), F("align", "align", "Align", "left"),
                               F("role", "role", "Color", "foreground")]),
    "processes":  ("Top processes", [F("count", "int", "How many", 3, (1, 10)),
                                     F("role", "role", "Color", "foreground")]),
    "uptime":     ("Uptime", [F("label", "text", "Label", "Uptime")]),
    "command":    ("Command output", [F("label", "text", "Label", "Kernel"),
                                      F("command", "text", "Shell command", "uname -r"),
                                      F("interval", "int", "Refresh (seconds)", 600, (1, 86400)),
                                      F("role", "role", "Color", "foreground")]),
    "separator":  ("Separator line", [F("role", "role", "Color", "muted")]),
    "spacer":     ("Empty space", [F("lines", "int", "Lines", 1, (1, 10))]),
}


def new_block(btype, **over):
    b = {"type": btype}
    for key, _kind, _label, default, _opts in BLOCK_TYPES[btype][1]:
        b[key] = default
    b.update(over)
    return b


def block_summary(b):
    title = BLOCK_TYPES[b["type"]][0]
    detail = {"clock": b.get("format"), "date": b.get("format"), "heading": b.get("text"),
              "text": b.get("text"), "cpu": b.get("style"), "memory": b.get("style"),
              "disk": b.get("path"), "network": b.get("iface") or "auto",
              "cputemp": "°F" if b.get("units") == "f" else "°C", "gpu": b.get("style"),
              "calendar": f"{b.get('start', 'sunday').capitalize()} first",
              "weather": b.get("location") or "auto", "processes": f"top {b.get('count')}",
              "command": b.get("command")}.get(b["type"])
    return f"{title}  ·  {detail}" if detail else title


WIDGET_TEMPLATES = [("system", "System monitor"), ("clock", "Clock & date"),
                    ("nowplaying", "Now playing"), ("weather", "Weather"), ("blank", "Blank")]


def widget_template(kind):
    w = {"id": uuid.uuid4().hex[:8], "name": "New widget", "alignment": "top_right", "gap_x": 40,
         "gap_y": 60, "width": 260, "font": "Noto Sans", "font_size": 10, "opacity": 70,
         "padding": 16, "interval": 1.0, "autostart": False, "blocks": []}
    if kind == "system":
        w.update(name="System monitor", blocks=[
            new_block("heading", text="SYSTEM"), new_block("cpu"), new_block("memory"),
            new_block("disk"), new_block("separator"), new_block("network"),
            new_block("separator"), new_block("processes"), new_block("uptime")])
    elif kind == "clock":
        w.update(name="Clock", alignment="top_left", width=320, opacity=0, gap_y=50,
                 blocks=[new_block("clock", size=64), new_block("date", size=14)])
    elif kind == "nowplaying":
        w.update(name="Now playing", alignment="bottom_left", width=300, gap_y=70,
                 blocks=[new_block("heading", text="NOW PLAYING", size=9), new_block("nowplaying")])
    elif kind == "weather":
        w.update(name="Weather", alignment="top_left", gap_y=220, width=280, blocks=[
            new_block("heading", text="WEATHER", size=9), new_block("weather", size=16)])
    return w


def normalize_widget(w):
    base = widget_template("blank")
    for k, v in base.items():
        w.setdefault(k, v)
    blocks = []
    for b in w.get("blocks", []):
        if b.get("type") in BLOCK_TYPES:
            nb = new_block(b["type"])
            nb.update({k: v for k, v in b.items() if k in nb})
            blocks.append(nb)
    w["blocks"] = blocks
    return w


def widget_path(w):
    return WIDGETS_DIR / f"{w['id']}.conf"


def esc(s):
    # '#' starts a comment in conky's text section; ']]' would close the Lua string
    return str(s).replace("#", "\\#").replace("]]", "] ]")


def conky_lines(b, w, p):
    t, fam = b["type"], w["font"]
    A = {"left": "", "center": "${alignc}", "right": "${alignr}"}.get(b.get("align", "left"), "")

    def C(role):
        return "${color%d}" % (COLOR_SLOTS.index(role) if role in COLOR_SLOTS else 0)

    def hx(role):
        return role_color(p, role).lstrip("#")

    def font(size, bold=False):
        return "${font %s:%ssize=%d}" % (fam, "bold:" if bold else "", size)

    def kv(label, value, lr="muted", vr="foreground"):
        return f"{C(lr)}{esc(label)}${{alignr}}{C(vr)}{value}"

    def graph(var, role):
        # explicit width: some conky versions draw a 0-width ("full width") graph as a sliver
        return f"${{{var} 28,{w['width']} {hx(role)} {hx('accent2' if role != 'accent2' else 'accent')}}}"

    def helper(*args):
        return " ".join([f"'{HELPER_PATH}'", *args])

    if t in ("clock", "date"):
        return [f"{A}{font(b['size'], b['bold'])}{C(b['role'])}${{time {esc(b['format'])}}}${{font}}"]
    if t in ("heading", "text"):
        return [f"{A}{font(b['size'], b['bold'])}{C(b['role'])}{esc(b['text'])}${{font}}"]
    if t == "cpu":
        out = [kv(b["label"], "${cpu cpu0}%")]
        if b["style"] == "bar":
            out.append(f"{C(b['role'])}${{cpubar cpu0 6}}")
        elif b["style"] == "graph":
            out.append(graph("cpugraph cpu0", b["role"]))
        return out
    if t == "memory":
        out = [kv(b["label"], "${mem} / ${memmax}")]
        if b["style"] == "bar":
            out.append(f"{C(b['role'])}${{membar 6}}")
        elif b["style"] == "graph":
            out.append(graph("memgraph", b["role"]))
        return out
    if t == "disk":
        P = b["path"].strip() or "/"
        out = [kv(b["label"], f"${{fs_used {P}}} / ${{fs_size {P}}}")]
        if b["style"] == "bar":
            out.append(f"{C(b['role'])}${{fs_bar 6 {P}}}")
        return out
    if t == "network":
        I = b["iface"].strip() or detect_iface() or "eth0"
        out = [kv(b["label_down"], f"${{downspeed {I}}}")]
        if b["style"] == "graph":
            out.append(graph(f"downspeedgraph {I}", b["role"]))
        out.append(kv(b["label_up"], f"${{upspeed {I}}}"))
        if b["style"] == "graph":
            out.append(graph(f"upspeedgraph {I}", b["role"]))
        return out
    if t == "cputemp":
        return [kv(b["label"], f"${{execi 5 {helper('cputemp', b['units'])}}}", vr=b["role"])]
    if t == "gpu":
        out = [kv(b["label"], f"${{execi 3 {helper('gpu', 'usage')}}}")]
        if b["style"] == "bar":
            out.append(f"{C(b['role'])}${{execibar 3 {helper('gpu', 'usage-raw')}}}")
        if b["temp"]:
            out.append(kv(f"{b['label']} temp", f"${{execi 5 {helper('gpu', 'temp', b['units'])}}}"))
        return out
    if t == "calendar":
        mono = "${font monospace:size=%d}" % b["size"]
        slot = COLOR_SLOTS.index(b["role"]) if b["role"] in COLOR_SLOTS else 1
        cmd = helper("calendar", b["start"], str(slot), b.get("align", "center"))
        return [f"{mono}${{execpi 600 {cmd}}}${{font}}"]
    if t == "nowplaying":
        title = "${execi 2 (playerctl metadata title 2>/dev/null || echo 'Nothing playing') | cut -c1-40}"
        artist = "${execi 2 playerctl metadata artist 2>/dev/null | cut -c1-44}"
        return [f"{A}{font(b['size'], True)}{C(b['role'])}{title}${{font}}", f"{A}{C('muted')}{artist}"]
    if t == "weather":
        loc = re.sub(r"[^\w,.+-]", "", b["location"].strip().replace(" ", "+"))
        unit = "u" if b["units"] == "us" else "m"
        cmd = f"curl -s --max-time 10 'wttr.in/{loc}?format=%t+%C&{unit}'"
        return [f"{A}{font(b['size'])}{C(b['role'])}${{execi {b['interval']} {cmd}}}${{font}}"]
    if t == "processes":
        return [f"{C(b['role'])}${{top name {i}}}${{alignr}}{C('muted')}${{top cpu {i}}}%"
                for i in range(1, b["count"] + 1)]
    if t == "uptime":
        return [kv(b["label"], "${uptime_short}")]
    if t == "command":
        v = f"${{execi {b['interval']} {esc(b['command'])}}}"
        return [kv(b["label"], v, vr=b["role"])] if b["label"].strip() else [f"{C(b['role'])}{v}"]
    if t == "separator":
        return [f"{C(b['role'])}${{hr 1}}"]
    if t == "spacer":
        return [""] * b["lines"]
    return []


def conky_config(w, p):
    cols = "\n".join(f"    color{i} = '{role_color(p, r).lstrip('#')}'," for i, r in enumerate(COLOR_SLOTS))
    text = "\n".join(line for b in w["blocks"] for line in conky_lines(b, w, p))
    alpha = round(w["opacity"] * 2.55)
    return f"""-- ThemeForge widget "{w['name']}" - generated file, edit it in ThemeForge instead
conky.config = {{
    alignment = '{w['alignment']}',
    gap_x = {w['gap_x']},
    gap_y = {w['gap_y']},
    minimum_width = {w['width']},
    maximum_width = {w['width']},
    update_interval = {w['interval']},
    double_buffer = true,
    background = false,
    own_window = true,
    own_window_type = 'normal',
    own_window_class = 'Conky',
    own_window_title = 'themeforge-{w['id']}',
    own_window_hints = 'undecorated,below,sticky,skip_taskbar,skip_pager',
    own_window_argb_visual = true,
    own_window_argb_value = {alpha},
    own_window_transparent = {'true' if alpha == 0 else 'false'},
    own_window_colour = '{p['background'].lstrip('#')}',
    border_inner_margin = {w['padding']},
    draw_borders = false,
    draw_outline = false,
    draw_shades = false,
    draw_graph_borders = false,
    use_xft = true,
    font = '{w['font']}:size={w['font_size']}',
    default_color = '{p['foreground'].lstrip('#')}',
{cols}
    cpu_avg_samples = 2,
    net_avg_samples = 2,
    no_buffers = true,
    format_human_readable = true,
    text_buffer_size = 4096,
}}

conky.text = [[
{text}
]]
"""


HELPER_PATH = CFG_DIR / "bin" / "tf-helper"
HELPER_SRC = r"""#!/usr/bin/env python3
# ThemeForge widget helper - generated by ThemeForge and overwritten when it changes.
#   tf-helper cputemp c|f
#   tf-helper gpu usage|usage-raw|temp [c|f]
#   tf-helper calendar sunday|monday <conky color slot> left|center|right
import calendar
import datetime
import glob
import shutil
import subprocess
import sys


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def fmt_temp(celsius, units):
    if celsius is None:
        return "n/a"
    return f"{round(celsius * 9 / 5 + 32)}°F" if units == "f" else f"{round(celsius)}°C"


def hwmon_temp(names, preferred=("tctl", "tdie", "package id 0", "edge", "junction")):
    for h in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read(h + "/name") not in names:
            continue
        first = None
        for inp in sorted(glob.glob(h + "/temp*_input")):
            v = read(inp)
            if v is None or not v.lstrip("-").isdigit():
                continue
            label = (read(inp.replace("_input", "_label")) or "").lower()
            if label in preferred:
                return int(v) / 1000
            first = first if first is not None else int(v) / 1000
        if first is not None:
            return first
    return None


def nvidia(query):
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3).stdout.strip().splitlines()
        return out[0].strip() if out and out[0].strip().replace(".", "").isdigit() else None
    except Exception:
        return None


def gpu_usage():
    v = nvidia("utilization.gpu")
    if v is not None:
        return int(float(v))
    for f in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        v = read(f)
        if v and v.isdigit():
            return int(v)
    return None


def gpu_temp():
    v = nvidia("temperature.gpu")
    if v is not None:
        return float(v)
    return hwmon_temp(("amdgpu", "nouveau", "radeon", "i915", "xe"))


def month(start, slot, align):
    today = datetime.date.today()
    first = 6 if start == "sunday" else 0
    A = {"center": "${alignc}", "right": "${alignr}"}.get(align, "")
    names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    names = names[first:] + names[:first]
    lines = [A + "${color%s}%s${color0}" % (slot, today.strftime("%B %Y").center(20).rstrip()),
             A + "${color3}" + " ".join(names) + "${color0}"]
    for week in calendar.Calendar(first).monthdayscalendar(today.year, today.month):
        cells = []
        for d in week:
            if d == 0:
                cells.append("  ")
            elif d == today.day:
                cells.append("${color%s}%2d${color0}" % (slot, d))
            else:
                cells.append("%2d" % d)
        lines.append(A + " ".join(cells))
    return "\n".join(lines)


def main(a):
    if not a:
        return ""
    if a[0] == "cputemp":
        return fmt_temp(hwmon_temp(("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz")),
                        a[1] if len(a) > 1 else "c")
    if a[0] == "gpu":
        what = a[1] if len(a) > 1 else "usage"
        if what == "temp":
            return fmt_temp(gpu_temp(), a[2] if len(a) > 2 else "c")
        u = gpu_usage()
        if what == "usage-raw":
            return str(u or 0)
        return "n/a" if u is None else f"{u}%"
    if a[0] == "calendar":
        return month(a[1] if len(a) > 1 else "sunday", a[2] if len(a) > 2 else "1",
                     a[3] if len(a) > 3 else "center")
    return ""


print(main(sys.argv[1:]))
"""


def ensure_helper():
    try:
        if HELPER_PATH.exists() and HELPER_PATH.read_text() == HELPER_SRC:
            return
    except OSError:
        pass
    HELPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    HELPER_PATH.write_text(HELPER_SRC)
    HELPER_PATH.chmod(0o755)


def write_widget(w, p):
    ensure_helper()
    WIDGETS_DIR.mkdir(parents=True, exist_ok=True)
    path = widget_path(w)
    path.write_text(conky_config(w, p))
    return path


SAMPLE_PROCS = [("firefox", "6.2"), ("kwin_wayland", "3.1"), ("plasmashell", "2.4"), ("kitty", "1.0"),
                ("cava", "0.8"), ("pipewire", "0.5"), ("steam", "0.4"), ("discord", "0.3"),
                ("baloo_file", "0.2"), ("dolphin", "0.1")]


def preview_rows(b, w, p):
    """Rough visual stand-in for what conky will draw."""
    t, al = b["type"], b.get("align", "left")
    if t in ("clock", "date"):
        try:
            s = time.strftime(b["format"])
        except Exception:
            s = b["format"]
        return [("text", s, b["role"], b["size"], b["bold"], al)]
    if t in ("heading", "text"):
        return [("text", re.sub(r"\$\{[^}]*\}", "…", b["text"]), b["role"], b["size"], b["bold"], al)]
    if t == "cpu":
        rows = [("kv", b["label"], "23%", "muted", "foreground")]
        if b["style"] == "bar":
            rows.append(("bar", 0.23, b["role"]))
        elif b["style"] == "graph":
            rows.append(("graph", 1, b["role"]))
        return rows
    if t == "memory":
        rows = [("kv", b["label"], "5.1GiB / 31.2GiB", "muted", "foreground")]
        if b["style"] == "bar":
            rows.append(("bar", 0.16, b["role"]))
        elif b["style"] == "graph":
            rows.append(("graph", 2, b["role"]))
        return rows
    if t == "disk":
        rows = [("kv", b["label"], "212GiB / 931GiB", "muted", "foreground")]
        if b["style"] == "bar":
            rows.append(("bar", 0.23, b["role"]))
        return rows
    if t == "network":
        rows = [("kv", b["label_down"], "1.4MiB", "muted", "foreground")]
        if b["style"] == "graph":
            rows.append(("graph", 3, b["role"]))
        rows.append(("kv", b["label_up"], "86KiB", "muted", "foreground"))
        if b["style"] == "graph":
            rows.append(("graph", 4, b["role"]))
        return rows
    if t == "cputemp":
        return [("kv", b["label"], "126°F" if b["units"] == "f" else "52°C", "muted", b["role"])]
    if t == "gpu":
        rows = [("kv", b["label"], "37%", "muted", "foreground")]
        if b["style"] == "bar":
            rows.append(("bar", 0.37, b["role"]))
        if b["temp"]:
            rows.append(("kv", f"{b['label']} temp", "135°F" if b["units"] == "f" else "57°C",
                         "muted", "foreground"))
        return rows
    if t == "calendar":
        import calendar as _cal
        today = time.localtime()
        first = 6 if b["start"] == "sunday" else 0
        names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        names = names[first:] + names[:first]
        rows = [("mono", [(time.strftime("%B %Y").center(20).rstrip(), b["role"])], b["size"], b["align"]),
                ("mono", [(" ".join(names), "muted")], b["size"], b["align"])]
        for week in _cal.Calendar(first).monthdayscalendar(today.tm_year, today.tm_mon):
            segs = []
            for i, d in enumerate(week):
                sep = " " if i else ""
                if d == today.tm_mday:
                    segs += [(sep, "foreground"), ("%2d" % d, b["role"])]
                else:
                    segs.append((sep + ("%2d" % d if d else "  "), "foreground"))
            rows.append(("mono", segs, b["size"], b["align"]))
        return rows
    if t == "nowplaying":
        return [("text", "Song title", b["role"], b["size"], True, al),
                ("text", "Artist name", "muted", w["font_size"], False, al)]
    if t == "weather":
        s = "+64°F Partly cloudy" if b["units"] == "us" else "+18°C Partly cloudy"
        return [("text", s, b["role"], b["size"], False, al)]
    if t == "processes":
        return [("kv", n, v + "%", b["role"], "muted") for n, v in SAMPLE_PROCS[:b["count"]]]
    if t == "uptime":
        return [("kv", b["label"], "3h 12m", "muted", "foreground")]
    if t == "command":
        out = f"‹{b['command']}›"
        if b["label"].strip():
            return [("kv", b["label"], out, "muted", b["role"])]
        return [("text", out, b["role"], w["font_size"], False, "left")]
    if t == "separator":
        return [("hr", b["role"])]
    if t == "spacer":
        return [("space", b["lines"])]
    return []


# ════════════════════════════════════════════════════════════════════
#  Desktop windows drawn by ThemeForge: music visualizers and panels
# ════════════════════════════════════════════════════════════════════

VIS_DIR = CFG_DIR / "visualizers"
PANELS_DIR = CFG_DIR / "panels"
LIVE_PALETTE_FILE = CFG_DIR / "live-palette.json"
ART_CACHE = HOME / ".cache" / "themeforge" / "art"
GLOW_MARGIN = 18


def write_live_palette(p):
    """The palette running visualizers and panels draw with (changes on Apply and in album-art mode)."""
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIVE_PALETTE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(p))
    tmp.replace(LIVE_PALETTE_FILE)


def read_live_palette(fallback):
    try:
        p = json.loads(LIVE_PALETTE_FILE.read_text())
        return p if valid_palette(p) else fallback
    except Exception:
        return fallback


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


# ── background processes (one per visualizer / panel, plus the tray service) ──

def tf_pids(flag, item_id=None):
    """PIDs of ThemeForge processes started with `flag` (and item_id), read from each process's real
    argument list so shells or editors that merely mention the command don't count."""
    try:
        out = subprocess.run(["pgrep", "-f", "themeforge"], capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    pids = []
    for tok in out.split():
        try:
            pid = int(tok)
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore").split("\0")
        except (ValueError, OSError):
            continue
        if pid == os.getpid() or flag not in argv:
            continue
        if not any(a.endswith("themeforge.py") or a.endswith("/themeforge") for a in argv[:argv.index(flag)]):
            continue
        i = argv.index(flag)
        if item_id is None or (i + 1 < len(argv) and argv[i + 1] == item_id):
            pids.append(pid)
    return pids


def start_tf_process(flag, item_id=None, x11=False, log_dir=None):
    log_dir = log_dir or CFG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if x11:
        env["QT_QPA_PLATFORM"] = "xcb"      # XWayland lets the window place itself
    args = [sys.executable, str(SCRIPT), flag] + ([item_id] if item_id else [])
    with open(log_dir / f"{item_id or flag.strip('-')}.log", "w") as log:
        subprocess.Popen(args, env=env, stdout=log, stderr=log, start_new_session=True)


def stop_tf_process(flag, item_id=None):
    for pid in tf_pids(flag, item_id):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def vis_pids(vid=None):
    return tf_pids("--visualizer", vid)


def start_visualizer(v):
    if not shutil.which("cava"):
        return False
    start_tf_process("--visualizer", v["id"], v.get("x11", True), VIS_DIR)
    return True


def stop_visualizer(vid):
    stop_tf_process("--visualizer", vid)


def panel_pids(pid=None):
    return tf_pids("--panel", pid)


def start_panel(panel):
    start_tf_process("--panel", panel["id"], panel.get("x11", True), PANELS_DIR)
    return True


def stop_panel(pid):
    stop_tf_process("--panel", pid)


# ── geometry ───────────────────────────────────────────────────────

def align_rect(alignment, gap_x, gap_y, W, H, g):
    vert, horiz = alignment.split("_")
    x = {"left": g.left() + gap_x, "middle": g.left() + (g.width() - W) / 2 + gap_x,
         "right": g.left() + g.width() - W - gap_x}[horiz]
    y = {"top": g.top() + gap_y, "middle": g.top() + (g.height() - H) / 2 + gap_y,
         "bottom": g.top() + g.height() - H - gap_y}[vert]
    return QRectF(x, y, W, H)


def screen_for(name):
    scr = next((s for s in QGuiApplication.screens() if s.name() == name), None)
    return scr or QGuiApplication.primaryScreen()


# ── panels ─────────────────────────────────────────────────────────

PANEL_KINDS = [("launcher", "Games launcher"), ("nowplaying", "Now playing card")]


def panel_template(kind="launcher"):
    p = {"id": uuid.uuid4().hex[:8], "kind": kind, "name": "Panel", "title": "", "alignment": "bottom_left",
         "gap_x": 40, "gap_y": 60, "width": 360, "opacity": 75, "radius": 14, "padding": 16, "border": True,
         "glow": False, "screen": "", "x11": True, "autostart": False,
         "folder": "~/Games", "columns": 4, "icon_size": 48, "labels": True,
         "art_size": 104, "controls": True, "progress": True}
    if kind == "launcher":
        p.update(name="Games", title="GAMES")
    else:
        p.update(kind="nowplaying", name="Now playing", title="NOW PLAYING", alignment="bottom_right",
                 gap_y=220, width=400)
    return p


def normalize_panel(panel):
    base = panel_template(panel.get("kind", "launcher"))
    for k, v in base.items():
        panel.setdefault(k, v)
    if panel["kind"] not in dict(PANEL_KINDS):
        panel["kind"] = "launcher"
    return panel


def parse_desktop_file(path):
    entry, main = {}, False
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return entry
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("["):
            main = st == "[Desktop Entry]"
        elif main and "=" in st and not st.startswith("#"):
            k, v = st.split("=", 1)
            entry.setdefault(k.strip(), v.strip())
    return entry


def launcher_items(folder):
    d = Path(os.path.expanduser(folder or ""))
    if not folder or not d.is_dir():
        return []
    items = []
    for f in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if f.name.startswith("."):
            continue
        if f.suffix == ".desktop":
            e = parse_desktop_file(f)
            if e.get("Hidden", "").lower() == "true" or e.get("NoDisplay", "").lower() == "true":
                continue
            items.append({"name": e.get("Name") or f.stem, "icon": e.get("Icon", ""), "path": str(f),
                          "type": "desktop"})
        elif f.is_dir():
            items.append({"name": f.name, "icon": "folder", "path": str(f), "type": "dir"})
        else:
            exe = os.access(f, os.X_OK)
            items.append({"name": f.stem if exe else f.name, "icon": "", "path": str(f),
                          "type": "exe" if exe else "file"})
    return items


_count_cache = {}


def panel_item_count(panel):
    if panel["kind"] != "launcher":
        return 0
    key = panel["folder"]
    hit = _count_cache.get(key)
    if hit and time.time() - hit[0] < 2:
        return hit[1]
    n = len(launcher_items(key))
    _count_cache[key] = (time.time(), n)
    return n


def desktop_exec_command(entry):
    cmd = re.sub(r"%[fFuUdDnNickvm]", "", entry.get("Exec", ""))
    return cmd.replace("%%", "%").strip()


def launch_item(item):
    path = item["path"]
    quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if item["type"] == "desktop":
        for tool in (["kioclient", "exec"], ["gio", "launch"]):
            if shutil.which(tool[0]):
                subprocess.Popen(tool + [path], **quiet)
                return True
        e = parse_desktop_file(path)
        if e.get("Type") == "Link" and e.get("URL"):
            subprocess.Popen(["xdg-open", e["URL"]], **quiet)
            return True
        cmd = desktop_exec_command(e)
        if cmd:
            subprocess.Popen(["sh", "-c", cmd], cwd=e.get("Path") or None, **quiet)
            return True
        return False
    if item["type"] == "exe":
        subprocess.Popen([path], cwd=str(Path(path).parent), **quiet)
        return True
    subprocess.Popen(["xdg-open", path], **quiet)
    return True


def panel_layout(panel, n_items=0):
    """Rects, relative to the panel's top-left corner, for everything on a panel; plus the full size."""
    pad, W = panel["padding"], max(120, panel["width"])
    lay = {}
    y = pad
    if panel["title"].strip():
        lay["title"] = QRectF(pad, y, W - 2 * pad, 16)
        y += 26
    if panel["kind"] == "launcher":
        cols = max(1, panel["columns"])
        cw = (W - 2 * pad) / cols
        ch = panel["icon_size"] + (32 if panel["labels"] else 14)
        rows = max(1, math.ceil(n_items / cols))
        lay["items"] = [QRectF(pad + (i % cols) * cw, y + (i // cols) * ch, cw, ch) for i in range(n_items)]
        lay["empty"] = QRectF(pad, y, W - 2 * pad, ch)
        y += rows * ch
    else:
        a = max(48, panel["art_size"])
        lay["art"] = QRectF(pad, y, a, a)
        x = pad + a + 16
        tw = max(40, W - pad - x)
        ty = y + 2
        lay["song"] = QRectF(x, ty, tw, 22)
        ty += 22
        lay["artist"] = QRectF(x, ty, tw, 18)
        ty += 26
        if panel["progress"]:
            lay["progress"] = QRectF(x, ty, tw, 5)
            lay["progress_hit"] = QRectF(x, ty - 6, tw, 17)
            lay["times"] = QRectF(x, ty + 8, tw, 14)
            ty += 28
        if panel["controls"]:
            bs, big = 30, 36
            cx = x + tw / 2
            lay["prev"] = QRectF(cx - big / 2 - 14 - bs, ty + (big - bs) / 2, bs, bs)
            lay["play"] = QRectF(cx - big / 2, ty, big, big)
            lay["next"] = QRectF(cx + big / 2 + 14, ty + (big - bs) / 2, bs, bs)
            ty += big
        y = max(y + a, ty)
    return lay, QRectF(0, 0, W, y + pad)


def panel_rect(panel, g, n_items=None):
    n = panel_item_count(panel) if n_items is None else n_items
    _lay, full = panel_layout(panel, n)
    return align_rect(panel["alignment"], panel["gap_x"], panel["gap_y"], full.width(), full.height(), g)


def panel_hit(panel, n_items, pos):
    lay, _ = panel_layout(panel, n_items)
    for i, r in enumerate(lay.get("items", [])):
        if r.contains(pos):
            return ("item", i)
    for key in ("prev", "play", "next"):
        if key in lay and lay[key].adjusted(-4, -4, 4, 4).contains(pos):
            return (key, None)
    if "progress_hit" in lay and lay["progress_hit"].contains(pos):
        r = lay["progress"]
        return ("seek", clamp((pos.x() - r.left()) / r.width()))
    return None


def fmt_time(sec):
    if sec is None or sec < 0:
        return "-:--"
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _font(size, bold=False):
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def _draw_transport_icon(qp, kind, r, col):
    qp.save()
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(col))
    c = r.center()
    s = r.width() * 0.22
    if kind in ("prev", "next"):
        d = -1 if kind == "prev" else 1
        tri = QPainterPath(QPointF(c.x() - d * s * 0.9, c.y() - s))
        tri.lineTo(c.x() + d * s * 0.7, c.y())
        tri.lineTo(c.x() - d * s * 0.9, c.y() + s)
        tri.closeSubpath()
        qp.drawPath(tri)
        qp.drawRect(QRectF(c.x() + d * s * 0.7 - (s * 0.28 if d > 0 else 0), c.y() - s, s * 0.28, 2 * s))
    elif kind == "pause":
        qp.drawRoundedRect(QRectF(c.x() - s * 0.85, c.y() - s, s * 0.6, 2 * s), 1, 1)
        qp.drawRoundedRect(QRectF(c.x() + s * 0.25, c.y() - s, s * 0.6, 2 * s), 1, 1)
    else:   # play
        tri = QPainterPath(QPointF(c.x() - s * 0.7, c.y() - s * 1.1))
        tri.lineTo(c.x() + s * 1.1, c.y())
        tri.lineTo(c.x() - s * 0.7, c.y() + s * 1.1)
        tri.closeSubpath()
        qp.drawPath(tri)
    qp.restore()


def paint_panel(qp, origin, panel, p, state):
    """Draw a panel with its top-left corner at origin. state: items, icons, hover, np, art, glow."""
    items = state.get("items", [])
    lay, full = panel_layout(panel, len(items))
    bg, fg, mu, ac = p["background"], p["foreground"], p["muted"], p["accent"]
    hover = state.get("hover")
    qp.save()
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setRenderHint(QPainter.SmoothPixmapTransform)
    qp.translate(origin)
    rad = panel["radius"]
    body = QPainterPath()
    body.addRoundedRect(full, rad, rad)

    glow = state.get("glow", 0.0) if panel["glow"] else 0.0
    if glow > 0.02:
        for k in range(6, 0, -1):
            grow = k * 3
            outer = QPainterPath()
            outer.addRoundedRect(full.adjusted(-grow, -grow, grow, grow), rad + grow, rad + grow)
            col = QColor(ac)
            col.setAlphaF(clamp(glow * 0.09))
            qp.fillPath(outer.subtracted(body), col)

    back = QColor(bg)
    back.setAlphaF(clamp(panel["opacity"] / 100))
    qp.fillPath(body, back)
    if panel["border"] or glow > 0.02:
        edge = QColor(mix(bg, ac, 0.4))
        if glow > 0.02:
            edge = QColor(mix(mix(bg, ac, 0.4), ac, clamp(glow)))
        qp.setPen(QPen(edge, 1.2))
        qp.setBrush(Qt.NoBrush)
        qp.drawPath(body)

    if "title" in lay:
        f = _font(8.5, True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        qp.setFont(f)
        qp.setPen(QColor(ac))
        qp.drawText(lay["title"], Qt.AlignLeft | Qt.AlignVCenter, panel["title"])

    if panel["kind"] == "launcher":
        icons = state.get("icons", {})
        isz = panel["icon_size"]
        if not items:
            qp.setFont(_font(9))
            qp.setPen(QColor(mu))
            qp.drawText(lay["empty"], Qt.AlignCenter | Qt.TextWordWrap,
                        f"Put game shortcuts in {panel['folder']}")
        for i, (it, r) in enumerate(zip(items, lay["items"])):
            if hover == ("item", i):
                hl = QColor(ac)
                hl.setAlphaF(0.2)
                qp.setPen(Qt.NoPen)
                qp.setBrush(hl)
                qp.drawRoundedRect(r.adjusted(3, 2, -3, -2), 8, 8)
            ic = icons.get(it["path"])
            ir = QRectF(r.center().x() - isz / 2, r.top() + 7, isz, isz)
            if ic is not None and not ic.isNull():
                ic.paint(qp, ir.toRect())
            else:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(mix(bg, ac, 0.5)))
                qp.drawRoundedRect(ir, isz * 0.22, isz * 0.22)
                qp.setPen(QColor(best_text(mix(bg, ac, 0.5), p)))
                qp.setFont(_font(isz * 0.3, True))
                qp.drawText(ir, Qt.AlignCenter, it["name"][:1].upper())
            if panel["labels"]:
                qp.setFont(_font(8.5))
                qp.setPen(QColor(fg if hover == ("item", i) else mix(fg, mu, 0.35)))
                lr = QRectF(r.left() + 3, ir.bottom() + 4, r.width() - 6, 16)
                text = QFontMetricsF(qp.font()).elidedText(it["name"], Qt.ElideRight, lr.width())
                qp.drawText(lr, Qt.AlignHCenter | Qt.AlignTop, text)
    else:
        np = state.get("np") or {}
        art = state.get("art")
        ar = lay["art"]
        clip = QPainterPath()
        clip.addRoundedRect(ar, 10, 10)
        qp.save()
        qp.setClipPath(clip)
        if art is not None and not art.isNull():
            pm = art.scaled(ar.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            qp.drawPixmap(ar, pm, QRectF((pm.width() - ar.width()) / 2, (pm.height() - ar.height()) / 2,
                                         ar.width(), ar.height()))
        else:
            g = QLinearGradient(ar.topLeft(), ar.bottomRight())
            _stops(g, p["gradient"])
            qp.fillRect(ar, g)
            qp.setPen(QColor(best_text(p["gradient"][0], p)))
            qp.setFont(_font(ar.height() * 0.3, True))
            qp.drawText(ar, Qt.AlignCenter, "♪")
        qp.restore()
        playing = np.get("status") == "Playing"
        title = np.get("title") or ("Nothing playing" if not np else "Unknown title")
        qp.setFont(_font(11.5, True))
        qp.setPen(QColor(fg))
        fm = QFontMetricsF(qp.font())
        qp.drawText(lay["song"], Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(title, Qt.ElideRight,
                                                                               lay["song"].width()))
        qp.setFont(_font(9.5))
        qp.setPen(QColor(ac))
        fm = QFontMetricsF(qp.font())
        qp.drawText(lay["artist"], Qt.AlignLeft | Qt.AlignVCenter,
                    fm.elidedText(np.get("artist") or "", Qt.ElideRight, lay["artist"].width()))
        if "progress" in lay:
            r = lay["progress"]
            length, pos = np.get("length"), np.get("position")
            frac = clamp(pos / length) if length and pos is not None else 0
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(mix(bg, fg, 0.18)))
            qp.drawRoundedRect(r, 2.5, 2.5)
            if frac > 0:
                g = QLinearGradient(r.topLeft(), r.topRight())
                _stops(g, [p["accent2"], p["accent"]])
                qp.setBrush(QBrush(g))
                qp.drawRoundedRect(QRectF(r.left(), r.top(), max(5, r.width() * frac), r.height()), 2.5, 2.5)
                if hover and hover[0] == "seek":
                    qp.setBrush(QColor(fg))
                    qp.drawEllipse(QPointF(r.left() + r.width() * frac, r.center().y()), 5, 5)
            qp.setFont(_font(8))
            qp.setPen(QColor(mu))
            qp.drawText(lay["times"], Qt.AlignLeft | Qt.AlignVCenter, fmt_time(pos) if np else "")
            qp.drawText(lay["times"], Qt.AlignRight | Qt.AlignVCenter, fmt_time(length) if np else "")
        for key in ("prev", "play", "next"):
            if key not in lay:
                continue
            r = lay[key]
            if key == "play":
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(mix(ac, fg, 0.15) if hover == ("play", None) else ac))
                qp.drawEllipse(r)
                _draw_transport_icon(qp, "pause" if playing else "play", r, best_text(ac, p))
            else:
                if hover == (key, None):
                    hl = QColor(ac)
                    hl.setAlphaF(0.22)
                    qp.setPen(Qt.NoPen)
                    qp.setBrush(hl)
                    qp.drawEllipse(r)
                _draw_transport_icon(qp, key, r, fg)
    qp.restore()
    return full


# ── album art / now playing data ───────────────────────────────────

NP_FORMAT = ("{{status}}\t{{xesam:title}}\t{{xesam:artist}}\t{{mpris:artUrl}}\t{{mpris:length}}\t"
             "{{position}}\t{{playerName}}")


def parse_np(out):
    line = (out or "").strip("\n").split("\n")[0]
    f = line.split("\t")
    if len(f) < 6 or f[0] not in ("Playing", "Paused", "Stopped"):
        return None

    def secs(v):
        try:
            return int(float(v)) / 1_000_000
        except ValueError:
            return None
    return {"status": f[0], "title": f[1], "artist": f[2], "art": f[3], "length": secs(f[4]),
            "position": secs(f[5]), "player": f[6] if len(f) > 6 else ""}


def fetch_art(url):
    """Local path for an MPRIS art URL (file:// or http[s]://, downloads are cached)."""
    from urllib.parse import unquote, urlparse
    if not url:
        return None
    if url.startswith("file://"):
        path = Path(unquote(urlparse(url).path))
        return path if path.is_file() else None
    if url.startswith("/"):
        return Path(url) if Path(url).is_file() else None
    if not url.startswith(("http://", "https://")):
        return None
    ART_CACHE.mkdir(parents=True, exist_ok=True)
    f = ART_CACHE / hashlib.sha1(url.encode()).hexdigest()
    if not f.exists():
        data = _http_get(url, timeout=10, limit=12 * 1024 * 1024)
        tmp = f.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(f)
        old = sorted(ART_CACHE.iterdir(), key=lambda x: x.stat().st_mtime)
        for stale in old[:-150]:
            stale.unlink(missing_ok=True)
    return f


class AudioFeed(QObject):
    """Runs cava in raw mode and emits each frame as a list of 0..1 values."""
    frame = Signal(list)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.cfg = VIS_DIR / f"{key}.cava"
        self.conf = None
        self.buf = b""
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda *_: QTimer.singleShot(2000, self._start))

    def configure(self, bars, framerate=60, smoothing=77, stereo=False):
        conf = (bars, framerate, smoothing, stereo)
        if conf == self.conf:
            return
        self.conf = conf
        VIS_DIR.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(cava_raw_config({"bars": bars, "framerate": framerate, "smoothing": smoothing,
                                             "stereo": stereo}))
        self.stop()
        self._start()

    def _start(self):
        if self.conf and self.proc.state() == QProcess.NotRunning and shutil.which("cava"):
            self.buf = b""
            self.proc.start("cava", ["-p", str(self.cfg)])

    def _read(self):
        self.buf += bytes(self.proc.readAllStandardOutput())
        if b"\n" not in self.buf:
            return
        *lines, self.buf = self.buf.split(b"\n")
        vals = parse_cava_frame(lines[-1].decode(errors="ignore"))
        if vals is not None:
            self.frame.emit(vals)

    def stop(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.blockSignals(True)
            self.proc.kill()
            self.proc.waitForFinished(1000)
            self.proc.blockSignals(False)


# ── visualizers ────────────────────────────────────────────────────

VIS_STYLES = [("bars", "Bars"), ("mirror", "Mirrored bars"), ("blocks", "LED blocks"),
              ("wave", "Wave"), ("mirrorwave", "Mirrored wave"), ("radial", "Radial ring"),
              ("frame", "Frame (around a panel)")]
VIS_COLORS = [("gradient", "Palette gradient"), ("accent", "Accent"), ("accent2", "Second accent"),
              ("foreground", "Text"), ("red", "Red"), ("green", "Green"), ("yellow", "Yellow"),
              ("blue", "Blue"), ("magenta", "Magenta"), ("cyan", "Cyan")]
VIS_TEMPLATES = [("bottom", "Bars along the bottom"), ("center", "Mirrored bars, centered"),
                 ("radial", "Radial ring"), ("wave", "Wave"), ("mirrorwave", "Mirrored wave"),
                 ("led", "LED meter"), ("frame", "Frame around a panel")]


def vis_template(kind="bottom"):
    v = {"id": uuid.uuid4().hex[:8], "name": "Visualizer", "style": "bars", "bars": 64, "gap": 25,
         "rounded": True, "stereo": False, "flip": False, "color": "gradient", "opacity": 90,
         "smoothing": 77, "framerate": 60, "alignment": "bottom_middle", "gap_x": 0, "gap_y": 0,
         "width": 0, "height": 160, "screen": "", "x11": True, "autostart": False,
         "glow": False, "wrap": "", "depth": 36}
    presets = {
        "bottom": dict(name="Bottom bars", bars=96, gap=30, height=150, opacity=85),
        "center": dict(name="Center bars", style="mirror", bars=72, width=1100, height=260,
                       alignment="middle_middle", stereo=True),
        "radial": dict(name="Radial ring", style="radial", bars=96, gap=35, width=440, height=440,
                       alignment="middle_right", gap_x=120, stereo=True, glow=True),
        "wave": dict(name="Wave", style="wave", bars=48, height=200, opacity=80),
        "mirrorwave": dict(name="Mirrored wave", style="mirrorwave", bars=48, width=1000, height=180,
                           alignment="top_middle", gap_y=80, stereo=True),
        "led": dict(name="LED meter", style="blocks", bars=24, gap=28, width=480, height=170,
                    alignment="bottom_left", gap_x=40, gap_y=60, rounded=False),
        "frame": dict(name="Panel frame", style="frame", bars=120, gap=40, depth=30, stereo=True, glow=True,
                      width=480, height=300, alignment="middle_middle"),
    }
    v.update(presets.get(kind, {}))
    return v


def normalize_vis(v):
    for k, val in vis_template().items():
        v.setdefault(k, val)
    if v["style"] not in dict(VIS_STYLES):
        v["style"] = "bars"
    return v


def vis_bar_count(v):
    n = max(4, int(v["bars"]))
    return n + (n % 2) if v["stereo"] else n      # cava wants an even count in stereo


def cava_raw_config(v):
    return "\n".join([
        "; Generated by ThemeForge for a desktop visualizer - edit it in ThemeForge instead",
        "[general]", f"bars = {vis_bar_count(v)}", f"framerate = {v['framerate']}", "autosens = 1", "",
        "[output]", "method = raw", "raw_target = /dev/stdout", "data_format = ascii",
        "ascii_max_range = 1000", "bar_delimiter = 59", "frame_delimiter = 10",
        f"channels = {'stereo' if v['stereo'] else 'mono'}", "mono_option = average", "",
        "[smoothing]", f"noise_reduction = {v['smoothing']}", ""])


def parse_cava_frame(line):
    line = line.strip().rstrip(";")
    if not line:
        return None
    try:
        return [clamp(int(x) / 1000) for x in line.split(";")]
    except ValueError:
        return None


def fake_spectrum(n, t, stereo=False):
    """Plausible-looking animated spectrum for previews."""
    half = (n + 1) // 2 if stereo else n
    vals = []
    for i in range(half):
        x = i / max(1, half - 1)
        env = 0.82 * math.exp(-x * 1.8) + 0.18
        wob = 0.55 + 0.45 * math.sin(t * 4.1 + i * 0.55) * math.cos(t * 2.3 - i * 0.21)
        beat = 0.72 + 0.28 * max(0.0, math.sin(t * 7.5))
        vals.append(clamp(env * wob * beat * 1.15, 0.02, 1.0))
    return (vals[::-1] + vals)[:n] if stereo else vals


def bass_level(vals, stereo=False):
    n = len(vals)
    if not n:
        return 0.0
    k = max(1, n // 10)
    half = max(1, k // 2)
    part = vals[n // 2 - half: n // 2 + half] if stereo else vals[:k]
    return sum(part) / max(1, len(part))


def wrapped_panel(v, panels):
    if not v.get("wrap"):
        return None
    return next((normalize_panel(dict(x)) for x in panels or [] if x.get("id") == v["wrap"]), None)


def vis_geometry(v, g, panels=None):
    """Where visualizer v sits inside screen rect g (QRectF). A frame wrapped around a panel hugs it."""
    panel = wrapped_panel(v, panels)
    if panel is not None:
        d = v["depth"] + 4
        return panel_rect(panel, g).adjusted(-d, -d, d, d)
    W = g.width() if v["width"] <= 0 else min(v["width"], g.width())
    H = min(v["height"], g.height())
    return align_rect(v["alignment"], v["gap_x"], v["gap_y"], W, H, g)


def _stops(grad, cols, start=0.0):
    if len(cols) == 1:
        grad.setColorAt(start, QColor(cols[0]))
        grad.setColorAt(1.0, QColor(cols[0]))
        return
    for i, c in enumerate(cols):
        grad.setColorAt(start + (1 - start) * i / (len(cols) - 1), QColor(c))


def _smooth_path(pts):
    path = QPainterPath(pts[0])
    for a, b in zip(pts, pts[1:]):
        mx = (a.x() + b.x()) / 2
        path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
    return path


def _perimeter_point(inner, s):
    """Point and outward angle at distance s clockwise from the top-left corner of a rectangle."""
    W, H = inner.width(), inner.height()
    s %= 2 * (W + H)
    if s < W:
        return QPointF(inner.left() + s, inner.top()), -90
    if s < W + H:
        return QPointF(inner.right(), inner.top() + s - W), 0
    if s < 2 * W + H:
        return QPointF(inner.right() - (s - W - H), inner.bottom()), 90
    return QPointF(inner.left(), inner.bottom() - (s - 2 * W - H)), 180


def _draw_vis(qp, rect, vals, v, cols, grow=0.0):
    n = len(vals)
    style, flip = v["style"], v["flip"]
    if v.get("wrap"):
        style = "frame"
    L, T, W, H = rect.left(), rect.top(), rect.width(), rect.height()
    slot = W / n
    bw = max(1.0, slot * (1 - v["gap"] / 100))
    op = qp.opacity()
    qp.setPen(Qt.NoPen)

    def box(r, rad):
        r = r.adjusted(-grow, -grow, grow, grow)
        rad = rad + grow if rad > 0.5 else 0
        if rad > 0.5:
            qp.drawRoundedRect(r, rad, rad)
        else:
            qp.drawRect(r)

    if style == "radial":
        qp.save()
        cx, cy = rect.center().x(), rect.center().y()
        R = min(W, H) / 2
        r0 = R * 0.42
        lmax = R - r0 - 2 - grow
        grad = QRadialGradient(QPointF(0, 0), R)
        _stops(grad, cols, start=r0 / R)
        qp.translate(cx, cy)
        if not grow:
            qp.setOpacity(op * 0.45)
            qp.setPen(QPen(QColor(cols[0]), 1.5))
            qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(QPointF(0, 0), r0 - 5, r0 - 5)
            qp.setOpacity(op)
            qp.setPen(Qt.NoPen)
        qp.setBrush(QBrush(grad))
        t = max(1.0, 2 * math.pi * r0 / n * (1 - v["gap"] / 100))
        for i, val in enumerate(vals):
            qp.save()
            qp.rotate(-90 + 360 * i / n)
            box(QRectF(r0, -t / 2, max(1.5, val * lmax), t), t / 2 if v["rounded"] else 0)
            qp.restore()
        qp.restore()
        return

    if style == "frame":
        d = v["depth"]
        inner = rect.adjusted(d + 4, d + 4, -(d + 4), -(d + 4))
        if inner.width() < 8 or inner.height() < 8:
            inner = rect.adjusted(W * 0.2, H * 0.2, -W * 0.2, -H * 0.2)
            d = min(W, H) * 0.18
        per = 2 * (inner.width() + inner.height())
        step = per / n
        t = max(1.0, step * (1 - v["gap"] / 100))
        grad = QLinearGradient(QPointF(0, 0), QPointF(d, 0))
        _stops(grad, cols)
        qp.setBrush(QBrush(grad))
        for i, val in enumerate(vals):
            pt, ang = _perimeter_point(inner, (i + 0.5) * step)
            qp.save()
            qp.translate(pt)
            qp.rotate(ang)
            box(QRectF(2, -t / 2, max(1.5, val * d), t), t / 2 if v["rounded"] else 0)
            qp.restore()
        return

    if style in ("mirror", "mirrorwave"):
        cy = T + H / 2
        grad = QLinearGradient(0, cy, 0, T)
        grad.setSpread(QGradient.ReflectSpread)
    else:
        grad = QLinearGradient(0, T, 0, T + H) if flip else QLinearGradient(0, T + H, 0, T)
    _stops(grad, cols)
    qp.setBrush(QBrush(grad))

    def bar_x(i):
        return L + i * slot + (slot - bw) / 2

    if style == "bars":
        for i, val in enumerate(vals):
            h = val * H
            if h >= 0.5:
                box(QRectF(bar_x(i), T if flip else T + H - h, bw, h),
                    min(bw / 2, h / 2) if v["rounded"] else 0)
    elif style == "mirror":
        for i, val in enumerate(vals):
            h = val * H / 2
            if h >= 0.25:
                box(QRectF(bar_x(i), cy - h, bw, 2 * h), min(bw / 2, h) if v["rounded"] else 0)
    elif style == "blocks":
        seg = max(3.0, min(bw * 0.55, H / 10))
        step = seg + max(1.5, seg * 0.45)
        total = max(1, int(H // step))
        for i, val in enumerate(vals):
            for k in range(int(round(val * total))):
                y = T + k * step if flip else T + H - k * step - seg
                box(QRectF(bar_x(i), y, bw, seg), min(bw, seg) / 2 if v["rounded"] else 1.0)
    elif style == "wave":
        edge = T if flip else T + H
        pts = [QPointF(L + (i + 0.5) * slot, T + val * H if flip else T + H - val * H)
               for i, val in enumerate(vals)]
        pts = [QPointF(L, pts[0].y())] + pts + [QPointF(L + W, pts[-1].y())]
        line = _smooth_path(pts)
        if not grow:
            fill = QPainterPath(line)
            fill.lineTo(L + W, edge)
            fill.lineTo(L, edge)
            fill.closeSubpath()
            qp.setOpacity(op * 0.65)
            qp.drawPath(fill)
            qp.setOpacity(op)
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(cols[-1]), 2.2 + grow * 2))
        qp.drawPath(line)
    elif style == "mirrorwave":
        top = [QPointF(L + (i + 0.5) * slot, cy - val * H / 2) for i, val in enumerate(vals)]
        top = [QPointF(L, cy)] + top + [QPointF(L + W, cy)]
        bottom = [QPointF(pt.x(), 2 * cy - pt.y()) for pt in reversed(top)]
        shape = _smooth_path(top + bottom[1:])
        shape.closeSubpath()
        if not grow:
            qp.setOpacity(op * 0.6)
            qp.drawPath(shape)
            qp.setOpacity(op)
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(cols[-1]), 1.8 + grow * 2))
        qp.drawPath(shape)


def paint_visualizer(qp, rect, vals, v, p):
    n = len(vals)
    if not n or rect.width() < 4 or rect.height() < 4:
        return
    cols = list(p["gradient"]) if v["color"] == "gradient" else [role_color(p, v["color"])]
    base_op = clamp(v["opacity"] / 100)
    qp.save()
    qp.setRenderHint(QPainter.Antialiasing)
    if v.get("glow"):
        bass = bass_level(vals, v["stereo"])
        for grow, strength in ((7, 0.10), (4, 0.16), (2, 0.22)):
            qp.setOpacity(base_op * strength * (0.3 + 1.2 * bass))
            _draw_vis(qp, rect, vals, v, cols, grow)
    qp.setOpacity(base_op)
    _draw_vis(qp, rect, vals, v, cols, 0)
    qp.restore()


class DesktopWindow(QWidget):
    """Base for ThemeForge's own desktop windows: frameless, kept below other windows,
    reloads itself when the settings or the live palette change."""

    def __init__(self, item_id, click_through):
        super().__init__()
        self.item_id = item_id
        flags = (Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint | Qt.WindowDoesNotAcceptFocus)
        if click_through:
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.stamp = None
        self.settings = None
        self.pal = None
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.check_reload)

    def check_reload(self):
        stamp = (_mtime(SETTINGS_FILE), _mtime(LIVE_PALETTE_FILE))
        if stamp == self.stamp:
            return True
        self.stamp = stamp
        self.settings = load_settings()
        self.pal = read_live_palette(self.settings["palette"])
        if not self.reload():
            QApplication.quit()
            return False
        self.update()
        return True

    def reload(self):
        return True

    def shutdown(self):
        pass


class VisualizerWindow(DesktopWindow):
    """Click-through desktop window that draws cava's output."""

    def __init__(self, vid):
        super().__init__(vid, click_through=True)
        self.setWindowTitle(f"themeforge-vis-{vid}")
        self.vals = []
        self.v = None
        self.feed = AudioFeed(vid, self)
        self.feed.frame.connect(self.on_frame)
        if not self.check_reload():
            raise SystemExit(f"No visualizer with id {vid}")
        self.poll.start()

    def reload(self):
        v = next((normalize_vis(x) for x in self.settings.get("visualizers", []) if x.get("id") == self.item_id),
                 None)
        if v is None:
            return False
        self.v = v
        self.feed.configure(vis_bar_count(v), v["framerate"], v["smoothing"], v["stereo"])
        panel = wrapped_panel(v, self.settings.get("panels"))
        scr = screen_for(panel["screen"] if panel else v["screen"])
        self.setGeometry(vis_geometry(v, QRectF(scr.availableGeometry()), self.settings.get("panels")).toRect())
        return True

    def on_frame(self, vals):
        self.vals = vals
        self.update()

    def paintEvent(self, e):
        if not self.v or not self.vals:
            return
        qp = QPainter(self)
        paint_visualizer(qp, QRectF(self.rect()), self.vals, self.v, self.pal)
        qp.end()

    def shutdown(self):
        self.feed.stop()


class PanelWindow(DesktopWindow):
    """Clickable desktop panel: a games launcher or a now playing card."""
    art_ready = Signal(str, object)

    def __init__(self, pid):
        super().__init__(pid, click_through=False)
        self.setWindowTitle(f"themeforge-panel-{pid}")
        self.setMouseTracking(True)
        self.panel = None
        self.items = []
        self.icons = {}
        self.hover = None
        self.np = None
        self.np_at = 0.0
        self.art_url = None
        self.art = None
        self.glow = 0.0
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda *_: self.load_items())
        self.feed = AudioFeed(f"panel-{pid}", self)
        self.feed.frame.connect(self.on_frame)
        self.np_proc = QProcess(self)
        self.np_proc.finished.connect(self.on_np)
        self.np_timer = QTimer(self)
        self.np_timer.setInterval(1000)
        self.np_timer.timeout.connect(self.poll_np)
        self.tick = QTimer(self)
        self.tick.setInterval(250)
        self.tick.timeout.connect(self.update)
        self.art_ready.connect(self.on_art)
        if not self.check_reload():
            raise SystemExit(f"No panel with id {pid}")
        self.poll.start()

    # ── settings
    def reload(self):
        panel = next((normalize_panel(x) for x in self.settings.get("panels", []) if x.get("id") == self.item_id),
                     None)
        if panel is None:
            return False
        old = self.panel
        self.panel = panel
        if panel["kind"] == "launcher":
            if not old or old["folder"] != panel["folder"]:
                self.load_items()
            self.np_timer.stop()
            self.tick.stop()
        else:
            self.items = []
            if not self.np_timer.isActive():
                self.np_timer.start()
                self.poll_np()
                self.tick.start()
        if panel["glow"]:
            self.feed.configure(12, 30, 70, False)
        else:
            self.feed.stop()
            self.feed.conf = None
            self.glow = 0.0
        self.place()
        return True

    def place(self):
        scr = screen_for(self.panel["screen"])
        r = panel_rect(self.panel, QRectF(scr.availableGeometry()), len(self.items))
        m = GLOW_MARGIN
        self.setGeometry(r.adjusted(-m, -m, m, m).toRect())

    # ── launcher
    def load_items(self):
        folder = Path(os.path.expanduser(self.panel["folder"]))
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if folder.is_dir():
            self.watcher.addPath(str(folder))
        self.items = launcher_items(self.panel["folder"])
        self.icons = {it["path"]: icon_for_item(it) for it in self.items}
        if self.panel:
            self.place()
        self.update()

    # ── now playing
    def poll_np(self):
        if self.np_proc.state() == QProcess.NotRunning and shutil.which("playerctl"):
            self.np_proc.start("playerctl", ["metadata", "--format", NP_FORMAT])

    def on_np(self, *_):
        out = bytes(self.np_proc.readAllStandardOutput()).decode(errors="ignore")
        self.np = parse_np(out)
        self.np_at = time.monotonic()
        url = (self.np or {}).get("art") or ""
        if url != self.art_url:
            self.art_url = url
            self.art = None
            if url:
                def work(u=url):
                    try:
                        path = fetch_art(u)
                    except Exception:
                        path = None
                    self.art_ready.emit(u, str(path) if path else "")
                threading.Thread(target=work, daemon=True).start()
        self.update()

    def on_art(self, url, path):
        if url == self.art_url:
            self.art = QPixmap(path) if path else None
            self.update()

    def live_np(self):
        if not self.np:
            return None
        np = dict(self.np)
        if np["status"] == "Playing" and np.get("position") is not None:
            np["position"] = np["position"] + (time.monotonic() - self.np_at)
            if np.get("length"):
                np["position"] = min(np["position"], np["length"])
        return np

    # ── audio glow
    def on_frame(self, vals):
        target = clamp(bass_level(vals) * 1.4)
        self.glow = self.glow * 0.6 + target * 0.4
        self.update()

    # ── drawing / input
    def paintEvent(self, e):
        if not self.panel:
            return
        qp = QPainter(self)
        paint_panel(qp, QPointF(GLOW_MARGIN, GLOW_MARGIN), self.panel, self.pal,
                    {"items": self.items, "icons": self.icons, "hover": self.hover, "np": self.live_np(),
                     "art": self.art, "glow": self.glow})
        qp.end()

    def hit(self, pos):
        return panel_hit(self.panel, len(self.items), QPointF(pos.x() - GLOW_MARGIN, pos.y() - GLOW_MARGIN))

    def mouseMoveEvent(self, e):
        h = self.hit(e.position())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.PointingHandCursor if h else Qt.ArrowCursor)
            if h and h[0] == "item":
                self.setToolTip(self.items[h[1]]["name"])
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.context_menu(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        h = self.hit(e.position())
        if not h:
            return
        kind, arg = h
        if kind == "item":
            launch_item(self.items[arg])
        elif kind in ("prev", "play", "next"):
            QProcess.startDetached("playerctl", [{"prev": "previous", "play": "play-pause", "next": "next"}[kind]])
            QTimer.singleShot(250, self.poll_np)
        elif kind == "seek" and self.np and self.np.get("length"):
            QProcess.startDetached("playerctl", ["position", f"{arg * self.np['length']:.1f}"])
            QTimer.singleShot(250, self.poll_np)

    def context_menu(self, pos):
        m = QMenu(self)
        if self.panel["kind"] == "launcher":
            folder = Path(os.path.expanduser(self.panel["folder"]))
            m.addAction("Open games folder").triggered.connect(
                lambda: (folder.mkdir(parents=True, exist_ok=True),
                         QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))))
            m.addAction("Refresh").triggered.connect(self.load_items)
        m.addAction("Edit in ThemeForge").triggered.connect(
            lambda: subprocess.Popen([sys.executable, str(SCRIPT)], start_new_session=True))
        m.addSeparator()
        m.addAction("Close this panel").triggered.connect(QApplication.quit)
        m.exec(pos)

    def shutdown(self):
        self.feed.stop()


def icon_for_item(it):
    ic = QIcon()
    name = it.get("icon") or ""
    if name.startswith("/") and Path(name).exists():
        ic = QIcon(name)
    elif name:
        ic = QIcon.fromTheme(name)
    if ic.isNull() and it["type"] != "desktop":
        ic = QFileIconProvider().icon(QFileInfo(it["path"]))
    return ic          # a null icon makes the panel draw a lettered tile in the accent color


def run_desktop_window(cls, item_id, flag):
    if tf_pids(flag, item_id):
        return          # already running
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ThemeForge")
    app.setQuitOnLastWindowClosed(False)
    win = cls(item_id)
    app.aboutToQuit.connect(win.shutdown)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()         # lets Python handle signals while Qt's loop runs
    tick.start(300)
    tick.timeout.connect(lambda: None)
    win.show()
    app.exec()


# ════════════════════════════════════════════════════════════════════
#  Auto-updater (GitHub releases)
# ════════════════════════════════════════════════════════════════════

def parse_version(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_git_checkout():
    return (SCRIPT.parent / ".git").exists()


def is_system_install():
    """Installed by dnf/rpm (e.g. from COPR) - the package manager does the updating."""
    return str(SCRIPT).startswith(("/usr/", "/opt/"))


COMMUNITY_INDEX_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/themes/index.json"


def fetch_community_themes():
    data = json.loads(_http_get(COMMUNITY_INDEX_URL))
    out = []
    for t in data.get("themes", []):
        p = t.get("palette", {})
        if valid_palette(p):
            p["name"] = t.get("name") or p.get("name") or "Community theme"
            out.append({"name": p["name"], "author": t.get("author", ""),
                        "description": t.get("description", ""), "palette": p})
    return out


def _http_get(url, timeout=15, limit=8 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": f"ThemeForge/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("download is unexpectedly large")
    return data


def fetch_latest_release():
    try:
        data = json.loads(_http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"no releases published yet on github.com/{GITHUB_REPO}") from None
        if e.code == 403:
            raise RuntimeError("GitHub rate limit reached - try again in an hour") from None
        raise RuntimeError(f"GitHub answered {e.code}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"couldn't reach GitHub ({e.reason})") from None
    tag = data["tag_name"]
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": data.get("body") or "",
            "url": data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
            "script": assets.get("themeforge.py")
            or f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/themeforge.py",
            "sha256": assets.get("themeforge.py.sha256")}


def check_for_update():
    """Newest release if it's newer than this copy, else None."""
    rel = fetch_latest_release()
    return rel if parse_version(rel["version"]) > parse_version(VERSION) else None


def install_update(rel):
    if is_git_checkout():
        raise RuntimeError("this copy is a git checkout - update it with `git pull` instead")
    if is_system_install():
        raise RuntimeError("ThemeForge was installed with dnf - update it with `sudo dnf upgrade themeforge`")
    data = _http_get(rel["script"])
    if rel.get("sha256"):
        expected = _http_get(rel["sha256"]).decode().split()[0].lower()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("the download didn't match its published checksum, so it wasn't installed")
    src = data.decode("utf-8")
    compile(src, "themeforge.py", "exec")           # refuse anything that isn't valid Python
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', src, re.M)
    if not m or parse_version(m.group(1)) != parse_version(rel["version"]):
        raise RuntimeError("the downloaded file's version doesn't match the release")
    if not os.access(SCRIPT.parent, os.W_OK) or not os.access(SCRIPT, os.W_OK):
        raise RuntimeError(f"no permission to replace {SCRIPT}")
    shutil.copy2(SCRIPT, SCRIPT.with_name(SCRIPT.name + ".bak"))
    tmp = SCRIPT.with_name(f".{SCRIPT.name}.new")
    tmp.write_bytes(data)
    os.chmod(tmp, SCRIPT.stat().st_mode)
    os.replace(tmp, SCRIPT)
    return rel["version"]


# ════════════════════════════════════════════════════════════════════
#  Targets (things that get themed)
# ════════════════════════════════════════════════════════════════════

def apply_kitty(p, s, log):
    d = HOME / ".config" / "kitty"
    d.mkdir(parents=True, exist_ok=True)
    a, sel_fg = p["ansi"], best_text(p["accent"], p)
    lines = ["# Generated by ThemeForge - rewritten every time you apply", f"# Palette: {p.get('name', 'custom')}", "",
             f"background {p['background']}", f"foreground {p['foreground']}",
             f"selection_background {p['accent']}", f"selection_foreground {sel_fg}",
             f"cursor {p['accent']}", f"cursor_text_color {p['background']}", f"url_color {p['accent2']}",
             f"active_border_color {p['accent']}", f"inactive_border_color {p['surface']}",
             f"bell_border_color {a[3]}",
             f"active_tab_background {p['accent']}", f"active_tab_foreground {sel_fg}",
             f"inactive_tab_background {p['surface']}", f"inactive_tab_foreground {p['muted']}",
             f"tab_bar_background {p['background']}", ""]
    lines += [f"color{i} {c}" for i, c in enumerate(a)]
    (d / "themeforge.conf").write_text("\n".join(lines) + "\n")

    conf = d / "kitty.conf"
    backup(conf)
    text = conf.read_text(errors="replace") if conf.exists() else ""
    marker = "# ThemeForge palette (keep this last so it wins)"
    kept = [ln for ln in text.splitlines() if ln.strip() not in ("include themeforge.conf", marker)]
    while kept and not kept[-1].strip():
        kept.pop()
    kept += ["", marker, "include themeforge.conf"]
    conf.write_text("\n".join(kept) + "\n")
    n = signal_procs("kitty", signal.SIGUSR1)
    log(f"✓ kitty - palette written, {n} open window(s) reloaded")


def apply_cava(p, s, log):
    path = HOME / ".config" / "cava" / "config"
    backup(path)
    lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    out, skip = [], False
    for line in lines:
        st = line.strip()
        if st.startswith("[") and "]" in st:
            skip = st.lower().startswith("[color]")
            if skip:
                continue
        if not skip:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    g = p["gradient"][:8] or [p["accent"]]
    sec = ["", "[color]", "; Generated by ThemeForge", "background = 'default'", f"foreground = '{g[0]}'"]
    if len(g) > 1:
        sec += ["gradient = 1", f"gradient_count = {len(g)}"]
        sec += [f"gradient_color_{i + 1} = '{c}'" for i, c in enumerate(g)]
    else:
        sec.append("gradient = 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out + sec) + "\n")
    n = signal_procs("cava", signal.SIGUSR1)
    log(f"✓ cava - {len(g)}-color gradient written, {n} running instance(s) reloaded")


_KDE_EFFECTS = """[ColorEffects:Disabled]
Color=56,56,56
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color=112,111,110
ColorAmount=0.025
ColorEffect=2
ContrastAmount=0.1
ContrastEffect=2
Enable=false
IntensityAmount=0
IntensityEffect=0
"""


def kde_colors(p, scheme):
    bg, sf, fg, mu, ac, ac2 = (p[k] for k in ("background", "surface", "foreground", "muted", "accent", "accent2"))
    an = p["ansi"]
    red, green, yellow, magenta = an[1], an[2], an[3], an[5]
    dark = is_dark(bg)
    sel_fg = best_text(ac, p)

    def c(h):
        return "%d,%d,%d" % hex_to_rgb(h)

    def sec(header, back, fore=fg, inactive=mu, active=ac):
        return "\n".join([
            f"[{header}]", f"BackgroundAlternate={c(mix(back, fore, 0.04))}", f"BackgroundNormal={c(back)}",
            f"DecorationFocus={c(ac)}", f"DecorationHover={c(ac)}", f"ForegroundActive={c(active)}",
            f"ForegroundInactive={c(inactive)}", f"ForegroundLink={c(ac2)}", f"ForegroundNegative={c(red)}",
            f"ForegroundNeutral={c(yellow)}", f"ForegroundNormal={c(fore)}", f"ForegroundPositive={c(green)}",
            f"ForegroundVisited={c(magenta)}", ""])

    header = mix(bg, sf, 0.5)
    parts = [
        _KDE_EFFECTS,
        sec("Colors:Button", sf),
        sec("Colors:Complementary", mix(bg, "#000000", 0.25)) if dark
        else sec("Colors:Complementary", fg, fore=bg, inactive=mix(bg, fg, 0.4)),
        sec("Colors:Header", header),
        sec("Colors:Header][Inactive", bg),
        sec("Colors:Selection", ac, fore=sel_fg, inactive=sel_fg, active=sel_fg),
        sec("Colors:Tooltip", sf),
        sec("Colors:View", kde_view_color(p)),
        sec("Colors:Window", bg),
        f"[General]\nColorScheme={scheme}\nName=ThemeForge ({p.get('name', 'custom')})\nshadeSortColumn=true\n",
        "[KDE]\ncontrast=4\n",
        f"[WM]\nactiveBackground={c(header)}\nactiveBlend={c(fg)}\nactiveForeground={c(fg)}\n"
        f"inactiveBackground={c(bg)}\ninactiveBlend={c(mu)}\ninactiveForeground={c(mu)}\n",
    ]
    return "\n".join(parts)


KDEGLOBALS = HOME / ".config" / "kdeglobals"


def apply_kde(p, s, log):
    current = ini_get(KDEGLOBALS, "General", "ColorScheme")
    if current and not current.startswith("ThemeForge") and not s.get("kde_original_scheme"):
        s["kde_original_scheme"] = current
    # Plasma ignores re-applying the scheme that's already active, so alternate between two names
    name = "ThemeForgeB" if current == "ThemeForgeA" else "ThemeForgeA"
    d = HOME / ".local" / "share" / "color-schemes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.colors").write_text(kde_colors(p, name))
    ok = run_cmd(["plasma-apply-colorscheme", name], log)
    log(("✓" if ok else "✗") + " KDE Plasma - color scheme " + ("applied" if ok else "written but not applied"))
    if ok and s.get("kde_accent", True):
        if "kde_original_accent" not in s:
            s["kde_original_accent"] = ini_get(KDEGLOBALS, "General", "AccentColor") or ""
        if run_cmd(["plasma-apply-colorscheme", "--accent-color", p["accent"]], lambda *_: None):
            log(f"   accent color set to {p['accent']}")
        else:
            log("   ! couldn't set the accent color (System Settings → Colors → Accent)")


def konsole_scheme(p):
    bg, fg, an = p["background"], p["foreground"], p["ansi"]
    out = []

    def block(name, col):
        out.extend([f"[{name}]", "Color=%d,%d,%d" % hex_to_rgb(col), ""])

    block("Background", bg)
    block("BackgroundFaint", bg)
    block("BackgroundIntense", p["surface"])
    for i in range(8):
        block(f"Color{i}", an[i])
        block(f"Color{i}Faint", mix(an[i], bg, 0.35))
        block(f"Color{i}Intense", an[i + 8])
    block("Foreground", fg)
    block("ForegroundFaint", p["muted"])
    block("ForegroundIntense", fg)
    out += ["[General]", "Blur=false", "ColorRandomization=false", "Description=ThemeForge",
            "Opacity=1", "Wallpaper=", ""]
    return "\n".join(out)


def apply_konsole(p, s, log):
    d = HOME / ".local" / "share" / "konsole"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ThemeForge.colorscheme").write_text(konsole_scheme(p))
    rc = HOME / ".config" / "konsolerc"
    prof = ini_get(rc, "Desktop Entry", "DefaultProfile")
    if prof and (d / prof).exists():
        backup(d / prof)
        ini_set(d / prof, "Appearance", "ColorScheme", "ThemeForge")
    else:
        pf = d / "ThemeForge.profile"
        if not pf.exists():
            pf.write_text("[Appearance]\nColorScheme=ThemeForge\n\n[General]\nName=ThemeForge\nParent=FALLBACK/\n")
        backup(rc)
        ini_set(rc, "Desktop Entry", "DefaultProfile", "ThemeForge.profile")
        prof = "ThemeForge.profile"
    log(f"✓ Konsole - scheme set on profile “{prof}” (new windows pick it up)")


def apply_widgets(p, s, log):
    procs = conky_procs()
    running = 0
    for w in s["widgets"]:
        path = write_widget(w, p)
        running += bool(conky_pids(path, procs))
    log(f"✓ Widgets - {len(s['widgets'])} regenerated, {running} running one(s) update live")


def apply_live(p, s, log):
    # running visualizers and panels watch this file and switch colors within a second
    write_live_palette(p)
    n = sum(bool(vis_pids(v["id"])) for v in s.get("visualizers", []))
    n += sum(bool(panel_pids(x["id"])) for x in s.get("panels", []))
    log(f"✓ Visualizers & panels - new colors handed to {n} running window(s)")


CONKY_KEYMAP = [("default_color", "foreground"), ("own_window_colour", "background"),
                ("color0", "foreground"), ("color1", "accent"), ("color2", "accent2"), ("color3", "muted"),
                ("color4", "red"), ("color5", "green"), ("color6", "yellow"), ("color7", "surface"),
                ("color8", "blue"), ("color9", "magenta")]


def recolor_conky(path, p):
    text = path.read_text(errors="replace")
    total = 0
    for key, role in CONKY_KEYMAP:
        hexv = role_color(p, role).lstrip("#")
        pat = re.compile(r"^(\s*%s)(\s*=\s*|\s+)(['\"]?)#?[0-9A-Fa-f]{6}(['\"]?)" % key, re.M)
        text, n = pat.subn(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{hexv}{m.group(4)}", text)
        total += n
    if total:
        backup(path)
        path.write_text(text)
    return total


def apply_external_conky(p, s, log):
    done = 0
    for e in s.get("external_conky", []):
        if not e.get("recolor"):
            continue
        path = Path(e["path"])
        if not path.exists():
            log(f"   ! {path} is missing")
            continue
        n = recolor_conky(path, p)
        log(f"   {path.name}: {n} color setting(s) updated" if n else
            f"   {path.name}: no color0-9 / default_color hex values found to replace")
        done += 1
    log(f"✓ Other conky configs - {done} recolored" if done else
        "- Other conky configs - none have “Recolor on Apply” turned on (Widgets tab)")


def apply_wallpaper(p, s, log):
    wp = s.get("wallpaper")
    if not wp or not Path(wp).exists():
        log("- Wallpaper - no image picked on the Colors tab")
        return
    ok = run_cmd(["plasma-apply-wallpaperimage", wp], log)
    log(("✓" if ok else "✗") + f" Wallpaper - {Path(wp).name}")


# ── icons ──────────────────────────────────────────────────────────

ICON_DIRS = [HOME / ".local" / "share" / "icons", HOME / ".icons", Path("/usr/share/icons")]
PAPIRUS_COLORS = {
    "black": "#4f4f4f", "blue": "#5294e2", "bluegrey": "#607d8b", "brown": "#ae8e6c", "carmine": "#a30002",
    "cyan": "#00bcd4", "darkcyan": "#45abb7", "deeporange": "#eb6637", "green": "#87b158", "grey": "#8e8e8e",
    "indigo": "#5c6bc0", "magenta": "#ca71df", "nordic": "#81a1c1", "orange": "#ee923a", "palebrown": "#d1bfae",
    "paleorange": "#eeca8f", "pink": "#f06292", "red": "#e25252", "teal": "#16a085", "violet": "#7e57c2",
    "white": "#e4e4e4", "yellow": "#f9bd30"}


def installed_icon_themes():
    """{name: directory} of icon themes that contain actual icons (not cursor-only)."""
    found = {}
    for base in ICON_DIRS:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            idx = d / "index.theme"
            if d.name in found or not idx.is_file():
                continue
            try:
                txt = idx.read_text(errors="replace")
            except OSError:
                continue
            if re.search(r"^Directories\s*=\s*\S", txt, re.M) and not re.search(r"^Hidden\s*=\s*true", txt, re.M | re.I):
                found[d.name] = d
    return found


PAPIRUS_NEUTRAL = ("black", "grey", "white")


def nearest_papirus_color(h):
    H, L, S = to_hls(h)
    if S < 0.18 or L > 0.92 or L < 0.1:            # greyish accent → pick by lightness among neutrals
        return min(PAPIRUS_NEUTRAL, key=lambda k: abs(to_hls(PAPIRUS_COLORS[k])[1] - L))

    def dist(k):
        h2, l2, s2 = to_hls(PAPIRUS_COLORS[k])
        return hue_dist(H, h2) * 4 + abs(L - l2) * 0.5 + abs(S - s2) * 0.3
    return min((k for k in PAPIRUS_COLORS if k not in PAPIRUS_NEUTRAL), key=dist)


def find_plasma_changeicons():
    for c in (shutil.which("plasma-changeicons"), "/usr/libexec/plasma-changeicons",
              "/usr/lib64/libexec/plasma-changeicons", "/usr/lib/libexec/plasma-changeicons",
              "/usr/lib/x86_64-linux-gnu/libexec/plasma-changeicons"):
        if c and os.access(c, os.X_OK):
            return c
    return None


def apply_icons(p, s, log):
    themes = installed_icon_themes()
    want = s.get("icon_theme") or ""
    current = ini_get(KDEGLOBALS, "Icons", "Theme") or "breeze"
    if want and want not in themes:
        log(f"   ! icon theme “{want}” isn't installed")
        want = ""
    if want and want != current:
        s.setdefault("icon_original_theme", current)
        tool = find_plasma_changeicons()
        if tool:
            run_cmd([tool, want], log)
        else:
            ini_set(KDEGLOBALS, "Icons", "Theme", want)
            run_cmd(["dbus-send", "--session", "--type=signal", "/KIconLoader",
                     "org.kde.KIconLoader.iconChanged", "int32:0"], lambda *_: None)
        log(f"   icon theme → {want}")
        current = want
    theme = want or current
    msg = f"✓ Icons - using {theme}"
    if s.get("papirus_folders", True) and theme.lower().startswith("papirus") and shutil.which("papirus-folders"):
        color = nearest_papirus_color(p["accent"])
        if s.get("papirus_color_applied") != f"{theme}:{color}":
            cmd = ["papirus-folders", "-C", color, "--theme", theme]
            tdir = themes.get(theme)
            if tdir and not os.access(tdir, os.W_OK):
                cmd = ["pkexec"] + cmd       # system-wide Papirus needs root; Plasma shows a password prompt
            if run_cmd(cmd, log):
                s["papirus_color_applied"] = f"{theme}:{color}"
                msg += f", folders recolored {color}"
            else:
                msg += " (folder color not changed)"
        else:
            msg += f", folders already {color}"
    log(msg)


# ── apps ───────────────────────────────────────────────────────────

def _rgba(h, a):
    r, g, b = hex_to_rgb(h)
    return f"rgba({r}, {g}, {b}, {a})"


def discord_css(p):
    bg, sf, fg, mu, ac, ac2 = (p[k] for k in ("background", "surface", "foreground", "muted", "accent", "accent2"))
    dark = is_dark(bg)
    lower = mix(bg, "#000000", 0.18) if dark else mix(bg, "#000000", 0.05)
    lowest = mix(bg, "#000000", 0.32) if dark else mix(bg, "#000000", 0.1)
    side = mix(bg, sf, 0.45)
    an = p["ansi"]
    v = {
        # classic names
        "--background-primary": bg, "--background-secondary": side, "--background-secondary-alt": lower,
        "--background-tertiary": lower, "--background-floating": lowest, "--background-nested-floating": lowest,
        "--background-accent": ac, "--background-message-hover": _rgba(fg, 0.035),
        "--background-modifier-hover": _rgba(fg, 0.06), "--background-modifier-active": _rgba(fg, 0.1),
        "--background-modifier-selected": _rgba(ac, 0.22), "--background-modifier-accent": _rgba(fg, 0.08),
        "--background-mobile-primary": bg, "--background-mobile-secondary": side,
        "--channeltextarea-background": sf, "--modal-background": bg, "--modal-footer-background": lower,
        "--text-normal": fg, "--text-muted": mu, "--text-link": ac2, "--text-positive": an[2],
        "--text-warning": an[3], "--text-danger": an[1], "--text-brand": ac,
        "--header-primary": fg, "--header-secondary": mu, "--channels-default": mu,
        "--interactive-normal": mix(fg, mu, 0.45), "--interactive-hover": fg, "--interactive-active": fg,
        "--interactive-muted": mix(mu, bg, 0.4), "--channel-icon": mu,
        "--brand-experiment": ac, "--brand-500": ac, "--brand-560": adjust(ac, -0.06),
        "--brand-600": adjust(ac, -0.1), "--brand-360": adjust(ac, 0.08), "--brand-260": adjust(ac, 0.15),
        "--scrollbar-thin-thumb": sf, "--scrollbar-auto-thumb": sf, "--scrollbar-auto-track": lower,
        "--scrollbar-auto-scrollbar-color-thumb": sf, "--scrollbar-auto-scrollbar-color-track": lower,
        "--input-background": sf, "--deprecated-card-bg": side,
        # 2025 "visual refresh" names
        "--background-base-low": bg, "--background-base-lower": lower, "--background-base-lowest": lowest,
        "--background-surface-high": side, "--background-surface-higher": sf,
        "--background-surface-highest": mix(sf, fg, 0.08), "--chat-background-default": bg,
        "--app-frame-background": lowest, "--bg-base-primary": bg, "--bg-base-secondary": side,
        "--bg-base-tertiary": lower, "--bg-surface-raised": sf, "--bg-surface-overlay": lowest,
        "--input-background-default": sf, "--text-default": fg, "--text-strong": fg, "--text-subtle": mu,
        "--border-subtle": _rgba(fg, 0.08), "--border-faint": _rgba(fg, 0.05), "--border-normal": _rgba(fg, 0.12),
        "--control-brand-foreground": ac, "--control-brand-foreground-new": ac,
        "--button-filled-brand-background": ac, "--button-filled-brand-background-hover": adjust(ac, -0.06),
        "--button-filled-brand-text": best_text(ac, p), "--mention-foreground": ac,
        "--mention-background": _rgba(ac, 0.18), "--info-help-foreground": ac2,
    }
    body = "\n".join(f"    {k}: {val} !important;" for k, val in v.items())
    return f"""/**
 * @name ThemeForge
 * @author ThemeForge
 * @description Colors from your ThemeForge palette ({p.get('name', 'custom')}). Rewritten every time you Apply.
 * @version {VERSION}
 * @source https://github.com/{GITHUB_REPO}
 */

:root, .theme-dark, .theme-light, .theme-darker, .theme-midnight,
.visual-refresh, .visual-refresh.theme-dark, .visual-refresh.theme-light {{
{body}
}}

::selection {{ background: {_rgba(ac, 0.35)}; }}
"""


DISCORD_THEME_DIRS = [  # (client, config dir); themes go in <dir>/themes
    ("Vencord", HOME / ".config" / "Vencord"),
    ("Vesktop", HOME / ".config" / "vesktop"),
    ("Vesktop (Flatpak)", HOME / ".var" / "app" / "dev.vencord.Vesktop" / "config" / "vesktop"),
    ("Equicord", HOME / ".config" / "Equicord"),
    ("Equibop", HOME / ".config" / "equibop"),
    ("BetterDiscord", HOME / ".config" / "BetterDiscord"),
]


def discord_clients():
    return [(name, d) for name, d in DISCORD_THEME_DIRS if d.is_dir()]


def apply_discord(p, s, log):
    clients = discord_clients()
    if not clients:
        log("- Discord - no Vencord, Vesktop, Equicord or BetterDiscord found (plain Discord can't load themes)")
        return
    css = discord_css(p)
    for name, d in clients:
        f = d / "themes" / "themeforge.theme.css"
        backup(f)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(css)
    names = ", ".join(n for n, _ in clients)
    log(f"✓ Discord - theme written for {names}. Turn on “ThemeForge” once in Discord → Settings → Themes; "
        "after that it updates live.")


def btop_theme(p):
    bg, sf, fg, mu, ac, ac2 = (p[k] for k in ("background", "surface", "foreground", "muted", "accent", "accent2"))
    an = p["ansi"]
    g = p["gradient"]
    lo, mid, hi = g[0], g[len(g) // 2], g[-1]
    t = {
        "main_bg": bg, "main_fg": fg, "title": fg, "hi_fg": ac, "selected_bg": sf, "selected_fg": ac,
        "inactive_fg": mu, "graph_text": mu, "meter_bg": sf, "proc_misc": ac2,
        "cpu_box": ac, "mem_box": ac2, "net_box": an[6], "proc_box": an[5], "div_line": sf,
        "temp_start": an[2], "temp_mid": an[3], "temp_end": an[1],
        "cpu_start": lo, "cpu_mid": mid, "cpu_end": hi,
        "free_start": an[2], "free_mid": an[2], "free_end": an[10],
        "cached_start": an[4], "cached_mid": an[4], "cached_end": an[12],
        "available_start": an[6], "available_mid": an[6], "available_end": an[14],
        "used_start": an[5], "used_mid": an[1], "used_end": an[9],
        "download_start": mix(ac2, bg, 0.5), "download_mid": ac2, "download_end": adjust(ac2, 0.1),
        "upload_start": mix(ac, bg, 0.5), "upload_mid": ac, "upload_end": adjust(ac, 0.1),
        "process_start": lo, "process_mid": mid, "process_end": hi,
    }
    return "# Generated by ThemeForge - rewritten every time you Apply\n" + "\n".join(
        f'theme[{k}]="{v}"' for k, v in t.items()) + "\n"


def apply_btop(p, s, log):
    d = HOME / ".config" / "btop"
    theme = d / "themes" / "themeforge.theme"
    backup(theme)
    theme.parent.mkdir(parents=True, exist_ok=True)
    theme.write_text(btop_theme(p))
    conf = d / "btop.conf"
    backup(conf)
    lines = conf.read_text(errors="replace").splitlines() if conf.exists() else []
    lines = [ln for ln in lines if not re.match(r"\s*color_theme\s*=", ln)]
    lines.append('color_theme = "themeforge"')
    conf.write_text("\n".join(lines) + "\n")
    log("✓ btop - theme written and selected (open btop again to see it)")


STARSHIP_NAMES = ["black", "red", "green", "yellow", "blue", "purple", "cyan", "white"]


def starship_palette(p):
    a = p["ansi"]
    rows = [f'{n} = "{a[i]}"' for i, n in enumerate(STARSHIP_NAMES)]
    rows += [f'bright-{n} = "{a[i + 8]}"' for i, n in enumerate(STARSHIP_NAMES)]
    rows += [f'{k} = "{p[k]}"' for k in ("background", "surface", "foreground", "muted", "accent", "accent2")]
    return rows


STARSHIP_MARK = "# Generated by ThemeForge - named colors in your prompt now follow your palette"


def starship_toml(text, p):
    out, skip, seen_table = [], False, False
    for ln in text.splitlines():
        st = ln.strip()
        if st == STARSHIP_MARK:
            continue
        if st.startswith("["):
            seen_table = True
            skip = st.replace(" ", "") in ("[palettes.themeforge]", "[palettes.'themeforge']",
                                           '[palettes."themeforge"]')
            if skip:
                continue
        if skip:
            continue
        if not seen_table and re.match(r"palette\s*=", st):
            continue
        if not st and out and not out[-1].strip():
            continue                    # collapse blank runs
        out.append(ln)
    first = next((i for i, ln in enumerate(out) if ln.strip().startswith("[")), len(out))
    head, tail = out[:first], out[first:]
    while head and not head[-1].strip():
        head.pop()
    while tail and not tail[-1].strip():
        tail.pop()
    head += ['palette = "themeforge"   # set by ThemeForge', ""]
    body = head + tail
    while body and not body[-1].strip():
        body.pop()
    body += ["", STARSHIP_MARK, "[palettes.themeforge]"] + starship_palette(p)
    return "\n".join(body) + "\n"


def apply_starship(p, s, log):
    path = Path(os.environ.get("STARSHIP_CONFIG") or HOME / ".config" / "starship.toml")
    backup(path)
    text = path.read_text(errors="replace") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(starship_toml(text, p))
    log("✓ Starship - palette set (named colors like red/blue/purple now use your theme; open a new prompt)")


def find_spicetify():
    for c in (shutil.which("spicetify"), str(HOME / ".spicetify" / "spicetify"),
              str(HOME / ".local" / "bin" / "spicetify")):
        if c and os.access(c, os.X_OK):
            return c
    return None


def spicetify_colors(p):
    bg, sf, fg, mu, ac, ac2 = (p[k] for k in ("background", "surface", "foreground", "muted", "accent", "accent2"))
    lower = mix(bg, "#000000", 0.25) if is_dark(bg) else mix(bg, "#000000", 0.06)
    c = {"text": fg, "subtext": mu, "main": bg, "sidebar": lower, "player": lower, "card": sf,
         "shadow": "#000000", "selected-row": fg, "button": ac, "button-active": adjust(ac, 0.06),
         "button-disabled": mu, "tab-active": sf, "notification": ac2, "notification-error": p["ansi"][1],
         "misc": mu}
    return "; Generated by ThemeForge\n[themeforge]\n" + "\n".join(
        f"{k:<19}= {v.lstrip('#')}" for k, v in c.items()) + "\n"


def apply_spotify(p, s, log):
    tool = find_spicetify()
    if not tool:
        log("- Spotify - Spicetify isn't installed (see spicetify.app)")
        return
    try:
        cfg_dir = subprocess.run([tool, "path", "userdata"], capture_output=True, text=True,
                                 timeout=15).stdout.strip().splitlines()[-1]
        tdir = Path(cfg_dir) / "Themes" / "ThemeForge"
    except Exception:
        tdir = HOME / ".config" / "spicetify" / "Themes" / "ThemeForge"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "color.ini").write_text(spicetify_colors(p))
    css = tdir / "user.css"
    if not css.exists():
        css.write_text("/* ThemeForge - colors come from color.ini; add your own tweaks here */\n")
    run_cmd([tool, "config", "current_theme", "ThemeForge", "color_scheme", "themeforge"], lambda *_: None)
    if s.get("spicetify_ready"):
        ok = run_cmd([tool, "refresh"], log)
    else:
        ok = run_cmd([tool, "backup", "apply"], log) or run_cmd([tool, "apply"], log)
        s["spicetify_ready"] = ok
    log(("✓" if ok else "✗") + " Spotify - Spicetify theme " + ("applied" if ok else "written, but spicetify failed"))


EXPORT_DIR = CFG_DIR / "exports"


def vivaldi_theme(p):
    return {
        "accentFromPage": False, "accentOnWindow": True, "accentSaturationLimit": 1, "alpha": 1,
        "backgroundImage": "", "backgroundPosition": "stretch", "blur": 0,
        "colorAccentBg": p["accent"], "colorBg": p["background"], "colorFg": p["foreground"],
        "colorHighlightBg": p["accent2"], "colorWindowBg": mix(p["background"], p["surface"], 0.5),
        "contrast": 0, "dimBlurred": False, "engineVersion": 1,
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "themeforge:" + json.dumps(p, sort_keys=True))),
        "name": f"ThemeForge - {p.get('name', 'custom')}", "preferSystemAccent": False, "radius": 6,
        "simpleScrollbar": True, "transparencyTabBar": False, "transparencyTabs": False, "url": "", "version": 1}


def apply_vivaldi(p, s, log):
    import zipfile
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORT_DIR / "ThemeForge-vivaldi.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("settings.json", json.dumps(vivaldi_theme(p), indent=2))
    log(f"✓ Vivaldi - theme saved to {out}. Import it in Vivaldi → Settings → Themes → Import "
        "(Vivaldi can't be themed from outside, so this step is manual).")


TARGETS = [
    ("kitty", "kitty", "Writes themeforge.conf, includes it from kitty.conf, live-reloads open windows", "kitty", apply_kitty),
    ("cava", "cava", "Rewrites the [color] section with your gradient and live-reloads", "cava", apply_cava),
    ("kde", "KDE Plasma", "Color scheme for apps, panels and title bars (GTK apps on Breeze follow it too)",
     "plasma-apply-colorscheme", apply_kde),
    ("konsole", "Konsole", "Color scheme, set on your default profile", "konsole", apply_konsole),
    ("widgets", "ThemeForge widgets", "Regenerates the widgets you built with the new colors", "conky", apply_widgets),
    ("visualizers", "Visualizers & panels", "Running visualizers, launchers and now playing cards switch colors",
     None, apply_live),
    ("conky", "Other conky configs", "Recolors conky files you added on the Widgets tab (opt-in per file)", "conky",
     apply_external_conky),
    ("wallpaper", "Wallpaper", "Sets the image you picked on the Colors tab", "plasma-apply-wallpaperimage",
     apply_wallpaper),
    ("icons", "Icons", "Switches icon theme and matches Papirus folder colors to your accent (options below)",
     None, apply_icons),
    ("discord", "Discord", "Theme for Vencord, Vesktop, Equicord or BetterDiscord", None, apply_discord),
    ("spotify", "Spotify", "Spicetify color scheme", find_spicetify, apply_spotify),
    ("btop", "btop", "Writes a btop theme and selects it", "btop", apply_btop),
    ("starship", "Starship prompt", "Palette for starship.toml - named colors follow your theme", "starship",
     apply_starship),
    ("vivaldi", "Vivaldi", "Exports a Vivaldi theme you import once per change", None, apply_vivaldi),
]


def target_available(exe):
    """(ok, label) for a target's required program; exe can be a name, a finder function or None."""
    if exe is None:
        return True, "ready"
    path = exe() if callable(exe) else shutil.which(exe)
    name = "spicetify" if callable(exe) else exe
    return (True, "installed") if path else (False, f"{name} not found")


def apply_all(s, log):
    p, done = s["palette"], 0
    for key, name, _desc, exe, fn in TARGETS:
        if not s["targets"].get(key):
            continue
        ok, why = target_available(exe)
        if not ok:
            log(f"- {name} - skipped, {why}")
            continue
        try:
            fn(p, s, log)
            done += 1
        except Exception as e:
            log(f"✗ {name} - failed: {e}")
    return done


def restore_originals(s, log):
    if ORIG_DIR.exists():
        for f in sorted(ORIG_DIR.rglob("*")):
            if f.is_dir():
                continue
            rel = str(f.relative_to(ORIG_DIR))
            if rel.endswith(".tf-absent"):
                target = HOME / rel[: -len(".tf-absent")]
                if target.exists():
                    target.unlink()
                    log(f"   removed {target} (didn't exist before ThemeForge)")
            else:
                target = HOME / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                log(f"   restored {target}")
        shutil.rmtree(ORIG_DIR, ignore_errors=True)
    else:
        log("   no config files to put back")
    orig = s.pop("kde_original_scheme", None)
    if orig:
        run_cmd(["plasma-apply-colorscheme", orig], log)
        log(f"   KDE color scheme back to {orig}")
    if "kde_original_accent" in s:
        acc = s.pop("kde_original_accent")
        if acc:
            r, g, b = (int(x) for x in acc.split(",")[:3])
            run_cmd(["plasma-apply-colorscheme", "--accent-color", rgb_to_hex((r, g, b))], log)
        else:
            tool = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
            if tool:
                run_cmd([tool, "--file", "kdeglobals", "--group", "General", "--key", "AccentColor", "--delete"],
                        lambda *_: None)
        log("   KDE accent color back to how it was")
    icons = s.pop("icon_original_theme", None)
    if icons:
        tool = find_plasma_changeicons()
        if tool:
            run_cmd([tool, icons], log)
        log(f"   icon theme back to {icons}")
    s.pop("spicetify_ready", None)
    signal_procs("kitty", signal.SIGUSR1)
    signal_procs("cava", signal.SIGUSR1)
    log("✓ Originals restored.")


# ════════════════════════════════════════════════════════════════════
#  Settings
# ════════════════════════════════════════════════════════════════════

def detect_conky_files():
    found = []
    rc = HOME / ".conkyrc"
    if rc.exists():
        found.append(rc)
    d = HOME / ".config" / "conky"
    if d.is_dir():
        found += sorted(d.glob("*.conf"))
    return [{"path": str(f), "recolor": False, "autostart": False} for f in found]


ALBUM_DEFAULTS = {"enabled": False, "targets": ["kitty", "cava", "widgets", "visualizers"], "light": False,
                  "revert": True}


def default_settings():
    return {"palette": copy.deepcopy(PRESETS["Catppuccin Mocha"]),
            "targets": {key: key in ("kitty", "cava", "kde", "widgets", "visualizers") for key, *_ in TARGETS},
            "wallpaper": "",
            "widgets": [widget_template("clock"), widget_template("system")],
            "visualizers": [vis_template("bottom")],
            "panels": [],
            "external_conky": detect_conky_files(),
            "profiles": [],
            "current_profile": "",
            "album": copy.deepcopy(ALBUM_DEFAULTS),
            "tray": False,
            "icon_theme": "",
            "papirus_folders": True,
            "kde_accent": True,
            "check_updates": True,
            "last_update_check": 0,
            "skip_version": ""}


def load_settings():
    s = default_settings()
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        targets = s["targets"]
        album = s["album"]
        s.update(data)
        targets.update(data.get("targets", {}))
        album.update(data.get("album") or {})
        s["targets"], s["album"] = targets, album
        if not valid_palette(s["palette"]):
            s["palette"] = copy.deepcopy(PRESETS["Catppuccin Mocha"])
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"ThemeForge: couldn't read settings ({e}); using defaults", file=sys.stderr)
    s.pop("visualizers_palette", None)          # replaced by live-palette.json in 2.2
    s["widgets"] = [normalize_widget(w) for w in s.get("widgets", [])]
    s["visualizers"] = [normalize_vis(v) for v in s.get("visualizers", [])]
    s["panels"] = [normalize_panel(x) for x in s.get("panels", [])]
    s["profiles"] = [x for x in s.get("profiles", []) if isinstance(x, dict) and x.get("name")
                     and valid_palette(x.get("palette", {}))]
    return s


_save_lock = threading.Lock()


def save_settings(s):
    with _save_lock:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(s, indent=2))
        tmp.replace(SETTINGS_FILE)


def service_wanted(s):
    return bool(s.get("tray") or s["album"].get("enabled"))


def update_autostart(s):
    wanted = (any(w.get("autostart") for w in s["widgets"])
              or any(e.get("autostart") for e in s.get("external_conky", []))
              or any(v.get("autostart") for v in s.get("visualizers", []))
              or any(x.get("autostart") for x in s.get("panels", []))
              or service_wanted(s))
    if wanted:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=ThemeForge (widgets, visualizers, tray)\n"
            f'Exec="{sys.executable}" "{SCRIPT}" --start-widgets\n'
            "X-KDE-autostart-after=panel\nNoDisplay=true\n")
    elif AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()


def start_autostart(s):
    procs = conky_procs()
    for w in s["widgets"]:
        if w.get("autostart"):
            path = write_widget(w, s["palette"])
            if not conky_pids(path, procs):
                start_conky(path)
    for e in s.get("external_conky", []):
        if e.get("autostart") and Path(e["path"]).exists() and not conky_pids(e["path"], procs):
            start_conky(e["path"])
    for v in s.get("visualizers", []):
        if v.get("autostart") and not vis_pids(v["id"]):
            start_visualizer(v)
    for x in s.get("panels", []):
        if x.get("autostart") and not panel_pids(x["id"]):
            start_panel(x)
    if service_wanted(s):
        ensure_service()


# ════════════════════════════════════════════════════════════════════
#  Profiles, album-art mode and the background service (tray icon)
# ════════════════════════════════════════════════════════════════════

BOOKKEEPING_KEYS = ("kde_original_scheme", "kde_original_accent", "icon_original_theme",
                    "papirus_color_applied", "spicetify_ready")
ALBUM_TARGETS = [("kitty", "kitty"), ("cava", "cava"), ("widgets", "Widgets"),
                 ("visualizers", "Visualizers & panels"), ("konsole", "Konsole"), ("discord", "Discord"),
                 ("btop", "btop"), ("kde", "KDE Plasma (slower, briefly redraws apps)")]
ALBUM_STATUS_FILE = CFG_DIR / "album-status.json"
SHORTCUT_DESKTOP = HOME / ".local" / "share" / "applications" / "themeforge-next-profile.desktop"
APPLY_LOCK = threading.RLock()


def apply_targets(p, s, keys, log):
    done = 0
    for key, name, _desc, exe, fn in TARGETS:
        if key not in keys:
            continue
        ok, _why = target_available(exe)
        if not ok:
            continue
        try:
            fn(p, s, log)
            done += 1
        except Exception as e:
            log(f"✗ {name} - failed: {e}")
    return done


def save_bookkeeping(applied):
    """Merge only ThemeForge's own bookkeeping into the settings file, so a background apply
    never overwrites edits made in the app at the same time."""
    fresh = load_settings()
    changed = False
    for k in BOOKKEEPING_KEYS:
        if k in applied and fresh.get(k) != applied[k]:
            fresh[k] = applied[k]
            changed = True
    if changed:
        save_settings(fresh)


def list_user_themes():
    return [f.stem for f in sorted(THEMES_DIR.glob("*.json"), key=lambda f: f.stem.lower())] \
        if THEMES_DIR.exists() else []


def load_user_theme(name):
    p = json.loads((THEMES_DIR / f"{name}.json").read_text())
    p["name"] = name
    if not valid_palette(p):
        raise ValueError("that theme file is missing some colors")
    return p


def running_state(s):
    procs = conky_procs()
    return {"widgets": [w["id"] for w in s["widgets"] if conky_pids(widget_path(w), procs)],
            "visualizers": [v["id"] for v in s["visualizers"] if vis_pids(v["id"])],
            "panels": [x["id"] for x in s["panels"] if panel_pids(x["id"])],
            "external_conky": [e["path"] for e in s.get("external_conky", []) if conky_pids(e["path"], procs)]}


def capture_profile(s, name):
    prof = {"name": name, "palette": copy.deepcopy(s["palette"]), "wallpaper": s.get("wallpaper", ""),
            "targets": dict(s["targets"]), "album": bool(s["album"]["enabled"]),
            "icon_theme": s.get("icon_theme", "")}
    prof.update(running_state(s))
    return prof


def save_profile(s, name):
    prof = capture_profile(s, name)
    for i, x in enumerate(s["profiles"]):
        if x["name"] == name:
            s["profiles"][i] = prof
            break
    else:
        s["profiles"].append(prof)
    s["current_profile"] = name
    return prof


def set_running(s, wanted):
    """Start/stop widgets, visualizers, panels and conky files so exactly `wanted` ones run."""
    procs = conky_procs()
    for w in s["widgets"]:
        path = widget_path(w)
        on, running = w["id"] in wanted.get("widgets", []), bool(conky_pids(path, procs))
        if on and not running:
            start_conky(write_widget(w, s["palette"]))
        elif running and not on:
            stop_conky(path)
    for e in s.get("external_conky", []):
        on, running = e["path"] in wanted.get("external_conky", []), bool(conky_pids(e["path"], procs))
        if on and not running and Path(e["path"]).exists():
            start_conky(e["path"])
        elif running and not on:
            stop_conky(e["path"])
    for v in s["visualizers"]:
        on, running = v["id"] in wanted.get("visualizers", []), bool(vis_pids(v["id"]))
        if on and not running:
            start_visualizer(v)
        elif running and not on:
            stop_visualizer(v["id"])
    for x in s["panels"]:
        on, running = x["id"] in wanted.get("panels", []), bool(panel_pids(x["id"]))
        if on and not running:
            start_panel(x)
        elif running and not on:
            stop_panel(x["id"])


def switch_profile(s, name, log):
    prof = next((x for x in s["profiles"] if x["name"] == name), None)
    if prof is None:
        raise ValueError(f"there's no profile called “{name}”")
    with APPLY_LOCK:
        s["palette"] = copy.deepcopy(prof["palette"])
        if prof.get("wallpaper"):
            s["wallpaper"] = prof["wallpaper"]
        s["targets"].update(prof.get("targets", {}))
        s["icon_theme"] = prof.get("icon_theme", s.get("icon_theme", ""))
        s["album"]["enabled"] = bool(prof.get("album"))
        s["current_profile"] = name
        log(f"— Switching to profile “{name}” at {time.strftime('%H:%M:%S')} —")
        apply_all(s, log)
        write_live_palette(s["palette"])
        set_running(s, prof)
        save_settings(s)
        update_autostart(s)
    if service_wanted(s):
        ensure_service()
    log(f"✓ Profile “{name}” is active")


def next_profile_name(s):
    names = [x["name"] for x in s["profiles"]]
    if not names:
        return None
    cur = s.get("current_profile")
    i = names.index(cur) if cur in names else -1
    return names[(i + 1) % len(names)]


def notify(title, body=""):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "ThemeForge", "-i", "preferences-desktop-color", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_shortcut_entry():
    SHORTCUT_DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    SHORTCUT_DESKTOP.write_text(
        "[Desktop Entry]\nType=Application\nName=ThemeForge: Next profile\n"
        "Comment=Switch to your next ThemeForge desktop profile\n"
        f'Exec="{sys.executable}" "{SCRIPT}" --next-profile\n'
        "Icon=preferences-desktop-color\nCategories=Settings;Utility;\nTerminal=false\n")
    subprocess.run(["update-desktop-database", str(SHORTCUT_DESKTOP.parent)], capture_output=True)
    return SHORTCUT_DESKTOP


def ensure_service():
    if not tf_pids("--service"):
        start_tf_process("--service", None, False, CFG_DIR)


def stop_everything(s):
    for w in s["widgets"]:
        stop_conky(widget_path(w))
    for v in s["visualizers"]:
        stop_visualizer(v["id"])
    for x in s["panels"]:
        stop_panel(x["id"])


def palette_icon(p, size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    r = QRectF(3, 3, size - 6, size - 6)
    cols = [p["accent"], p["accent2"], p["ansi"][5], p["ansi"][6]]
    for i, c in enumerate(cols):
        path = QPainterPath(r.center())
        path.arcTo(r, 90 - i * 90, -90)
        path.closeSubpath()
        qp.fillPath(path, QColor(c))
    qp.setPen(QPen(QColor(p["background"]), size * 0.08))
    qp.setBrush(QColor(p["background"]))
    qp.drawEllipse(r.center(), size * 0.17, size * 0.17)
    qp.end()
    return QIcon(pm)


class AlbumArtWatcher(QObject):
    """Recolors the album-art targets whenever a new cover starts playing."""
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.last_art = None
        self.active = False
        self.idle_since = None
        self.busy = False
        self.pending = None
        self.proc = QProcess(self)
        self.proc.finished.connect(self.on_np)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        self.finished.connect(self.on_finished)

    def set_enabled(self, on):
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            self.last_art = None
            self.timer.start()
            self.poll()
        else:
            self.timer.stop()
            if self.active:
                self.run(None)

    def poll(self):
        if self.proc.state() == QProcess.NotRunning and shutil.which("playerctl"):
            self.proc.start("playerctl", ["metadata", "--format", NP_FORMAT])

    def on_np(self, *_):
        if not self.enabled:
            return
        np = parse_np(bytes(self.proc.readAllStandardOutput()).decode(errors="ignore"))
        if np and np["status"] == "Playing" and np["art"]:
            self.idle_since = None
            if np["art"] != self.last_art:
                self.last_art = np["art"]
                self.run(np)
        elif self.active:
            self.idle_since = self.idle_since or time.monotonic()
            s = load_settings()
            if s["album"].get("revert", True) and time.monotonic() - self.idle_since > 15:
                self.last_art = None
                self.run(None)

    def run(self, np):
        """np=None means go back to the user's own theme."""
        if self.busy:
            self.pending = ("np", np)
            return
        self.busy = True
        threading.Thread(target=self.work, args=(np,), daemon=True).start()

    def work(self, np):
        try:
            s = load_settings()
            keys = s["album"].get("targets", [])
            if np is None:
                p = s["palette"]
                status = {"state": "off", "time": time.time()}
            else:
                path = fetch_art(np["art"])
                if not path:
                    raise RuntimeError("couldn't get the album art")
                p = palette_from_wallpaper(path, s["album"].get("light", False))
                p["name"] = f"♪ {np['title'] or 'Now playing'}"
                status = {"state": "on", "title": np["title"], "artist": np["artist"], "time": time.time(),
                          "palette": p}
            with APPLY_LOCK:
                apply_targets(p, s, keys, print)
                save_bookkeeping(s)
            self.active = np is not None
            ALBUM_STATUS_FILE.write_text(json.dumps(status))
        except Exception as e:
            print(f"album-art mode: {e}", file=sys.stderr)
        finally:
            self.finished.emit()

    def on_finished(self):
        self.busy = False
        if self.pending:
            _, np = self.pending
            self.pending = None
            if self.enabled or np is None:
                self.run(np)


class Service(QObject):
    """Background process: tray icon + album-art mode. Exits when neither is switched on."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.tray = None
        self.menu = None
        self.stamp = None
        self.album = AlbumArtWatcher(self)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.sync)
        self.timer.start()
        self.sync()

    def sync(self):
        stamp = (_mtime(SETTINGS_FILE), _mtime(LIVE_PALETTE_FILE))
        if stamp == self.stamp:
            return
        self.stamp = stamp
        s = load_settings()
        if not service_wanted(s):
            self.album.set_enabled(False)
            QTimer.singleShot(3000 if self.album.busy else 0, self.app.quit)
            return
        self.album.set_enabled(bool(s["album"].get("enabled")))
        if s.get("tray") and not QSystemTrayIcon.isSystemTrayAvailable():
            self.stamp = None           # the panel's tray isn't up yet (e.g. right after login) - retry
            return
        if s.get("tray"):
            if self.tray is None:
                self.tray = QSystemTrayIcon(self)
                self.tray.activated.connect(self.on_activated)
            self.tray.setIcon(palette_icon(read_live_palette(s["palette"])))
            prof = s.get("current_profile")
            self.tray.setToolTip("ThemeForge" + (f" — {prof}" if prof else "") + f"\n{s['palette'].get('name', '')}")
            self.build_menu(s)
            self.tray.show()
        elif self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def build_menu(self, s):
        m = QMenu()
        m.addAction("Open ThemeForge").triggered.connect(open_app)
        m.addSeparator()
        pm = m.addMenu("Profiles")
        if s["profiles"]:
            for x in s["profiles"]:
                a = pm.addAction(x["name"].replace("&", "&&"))
                a.setCheckable(True)
                a.setChecked(x["name"] == s.get("current_profile"))
                a.triggered.connect(lambda *_, n=x["name"]: self.in_background(self.do_profile, n))
            pm.addSeparator()
            pm.addAction("Next profile").triggered.connect(
                lambda *_: self.in_background(self.do_profile, None))
        else:
            pm.addAction("No profiles yet - save one in ThemeForge").setEnabled(False)
        tm = m.addMenu("Themes")
        for name in PRESETS:
            tm.addAction(name).triggered.connect(lambda *_, n=name: self.in_background(self.do_theme, n, False))
        users = list_user_themes()
        if users:
            tm.addSeparator()
            for name in users:
                tm.addAction(f"★ {name}").triggered.connect(
                    lambda *_, n=name: self.in_background(self.do_theme, n, True))
        a = m.addAction("Match album art")
        a.setCheckable(True)
        a.setChecked(bool(s["album"].get("enabled")))
        a.toggled.connect(self.toggle_album)
        m.addSeparator()
        m.addAction("Apply my theme again").triggered.connect(
            lambda *_: self.in_background(lambda: apply_all(load_settings(), print)))
        m.addAction("Stop widgets, visualizers && panels").triggered.connect(
            lambda *_: stop_everything(load_settings()))
        m.addSeparator()
        m.addAction("Hide tray icon").triggered.connect(self.hide_tray)
        self.menu = m
        self.tray.setContextMenu(m)

    def on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            open_app()
        elif reason == QSystemTrayIcon.MiddleClick:
            self.in_background(self.do_profile, None)

    def in_background(self, fn, *args):
        threading.Thread(target=lambda: self._guard(fn, *args), daemon=True).start()

    @staticmethod
    def _guard(fn, *args):
        try:
            with APPLY_LOCK:
                fn(*args)
        except Exception as e:
            notify("ThemeForge", str(e))

    @staticmethod
    def do_profile(name):
        s = load_settings()
        name = name or next_profile_name(s)
        if not name:
            notify("ThemeForge", "You haven't saved any profiles yet.")
            return
        switch_profile(s, name, print)
        notify(f"Profile: {name}")

    @staticmethod
    def do_theme(name, user):
        s = load_settings()
        s["palette"] = load_user_theme(name) if user else copy.deepcopy(PRESETS[name])
        apply_all(s, print)
        save_settings(s)

    @staticmethod
    def toggle_album(on):
        s = load_settings()
        s["album"]["enabled"] = on
        save_settings(s)
        update_autostart(s)

    @staticmethod
    def hide_tray():
        s = load_settings()
        s["tray"] = False
        save_settings(s)
        update_autostart(s)


def open_app():
    subprocess.Popen([sys.executable, str(SCRIPT)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_service():
    if tf_pids("--service"):
        return
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ThemeForge")
    app.setDesktopFileName("themeforge")
    app.setQuitOnLastWindowClosed(False)
    svc = Service(app)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(300)
    tick.timeout.connect(lambda: None)
    app.exec()
    svc.album.set_enabled(False)


# ════════════════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════════════════

def app_qss(p):
    bg, sf, fg, mu, ac = (p[k] for k in ("background", "surface", "foreground", "muted", "accent"))
    sel_fg, view, line = best_text(ac, p), kde_view_color(p), mix(sf, fg, 0.12)
    return f"""
    QWidget {{ background: {bg}; color: {fg}; font-size: 10pt; }}
    QLabel#title {{ font-size: 18pt; font-weight: bold; }}
    QLabel#muted, QLabel#hint {{ color: {mu}; }}
    QLabel#warn {{ color: {p["ansi"][3]}; }}
    QLabel#section {{ color: {mu}; font-weight: bold; letter-spacing: 1px; padding-top: 6px; }}
    QLabel#thumb {{ background: {view}; border: 1px dashed {line}; border-radius: 6px; color: {mu}; }}
    QTabWidget::pane {{ border: 1px solid {sf}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {mu}; padding: 8px 18px; border: none;
                    border-bottom: 2px solid transparent; font-weight: bold; }}
    QTabBar::tab:selected {{ color: {fg}; border-bottom: 2px solid {ac}; }}
    QTabBar::tab:hover {{ color: {fg}; }}
    QPushButton, QToolButton {{ background: {sf}; color: {fg}; border: 1px solid {line};
                                border-radius: 6px; padding: 6px 12px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {ac}; }}
    QPushButton:disabled {{ color: {mu}; }}
    QPushButton#primary {{ background: {ac}; color: {sel_fg}; border: none; font-weight: bold; padding: 7px 16px; }}
    QPushButton#primary:hover {{ background: {mix(ac, fg, 0.15)}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {{
        background: {view}; border: 1px solid {line}; border-radius: 6px; padding: 4px 6px;
        selection-background-color: {ac}; selection-color: {sel_fg}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 22px; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ac}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
    QCheckBox:disabled {{ color: {mu}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {mix(line, fg, 0.35)};
                           border-radius: 4px; background: {view}; }}
    QCheckBox::indicator:checked {{ background: {ac}; border-color: {ac}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {line}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {mu}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {line}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QComboBox QAbstractItemView {{ background: {sf}; border: 1px solid {line}; }}
    QListWidget::item {{ padding: 6px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: {ac}; color: {sel_fg}; }}
    QGroupBox {{ border: 1px solid {sf}; border-radius: 8px; margin-top: 16px; padding: 12px 10px 10px 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {mu}; font-weight: bold; }}
    QScrollArea {{ border: none; }}
    QSplitter::handle {{ background: {bg}; width: 8px; }}
    QMenu {{ background: {sf}; border: 1px solid {line}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {ac}; color: {sel_fg}; }}
    QStatusBar {{ color: {mu}; }}
    QFrame#banner {{ background: {mix(bg, ac, 0.18)}; border: 1px solid {mix(bg, ac, 0.45)};
                     border-radius: 8px; }}
    QFrame#banner QLabel {{ background: transparent; }}
    QCheckBox {{ spacing: 8px; }}
    """


def section_label(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


def hint_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


def spin(lo, hi, suffix=""):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSuffix(suffix)
    return s


def color_icon(h):
    pm = QPixmap(14, 14)
    pm.fill(QColor(h))
    return QIcon(pm)


class SwatchButton(QPushButton):
    colorPicked = Signal(str)

    def __init__(self, color="#000000", compact=False):
        super().__init__()
        self.compact = compact
        self.color = color
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.clicked.connect(self.pick)
        self.customContextMenuRequested.connect(self.menu)
        if compact:
            self.setFixedSize(38, 30)
        self.set_color(color)

    def set_color(self, c):
        self.color = c
        self.setText("" if self.compact else c)
        self.setToolTip(f"{c}\nClick to change · right-click to type or copy hex")
        edge = mix(c, "#808080", 0.4)
        self.setStyleSheet(
            f"QPushButton {{ background: {c}; color: {text_on(c)}; border: 1px solid {edge};"
            f" border-radius: 6px; padding: 6px 8px; font-family: monospace; }}"
            f" QPushButton:hover {{ border: 2px solid {text_on(c)}; }}")

    def pick(self):
        col = QColorDialog.getColor(QColor(self.color), self, "Pick a color")
        if col.isValid():
            self._emit(col.name())

    def _emit(self, c):
        self.set_color(c)
        self.colorPicked.emit(c)

    def menu(self, pos):
        m = QMenu(self)
        a_hex = m.addAction("Type a hex value…")
        a_copy = m.addAction("Copy hex")
        act = m.exec(self.mapToGlobal(pos))
        if act == a_hex:
            txt, ok = QInputDialog.getText(self, "Hex color", "Color (#rrggbb):", text=self.color)
            if ok and valid_hex(txt):
                self._emit(norm_hex(txt))
        elif act == a_copy:
            QApplication.clipboard().setText(self.color)


# ── palette preview (mock KDE window + kitty running cava) ─────────

class PalettePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.pal = None
        self.t = 0.0
        self.setMinimumSize(440, 520)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)

    def set_palette(self, p):
        self.pal = p
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def tick(self):
        self.t += 0.05
        self.update()

    def paintEvent(self, e):
        if not self.pal:
            return
        p = self.pal
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor(mix(p["background"], "#000000", 0.35)))
        r = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        kh = r.height() * 0.47
        self.draw_kde(qp, QRectF(r.left(), r.top(), r.width(), kh), p)
        self.draw_term(qp, QRectF(r.left(), r.top() + kh + 14, r.width(), r.height() - kh - 14), p)
        qp.end()

    @staticmethod
    def _font(size, bold=False):
        f = QFont()
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def draw_kde(self, qp, r, p):
        bg, sf, fg, mu, ac = (p[k] for k in ("background", "surface", "foreground", "muted", "accent"))
        an, sel_fg, view = p["ansi"], best_text(ac, p), kde_view_color(p)
        qp.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        qp.setClipPath(clip)
        qp.fillRect(r, QColor(bg))

        tb = QRectF(r.left(), r.top(), r.width(), 32)
        qp.fillRect(tb, QColor(mix(bg, sf, 0.5)))
        qp.setFont(self._font(9, True))
        qp.setPen(QColor(fg))
        qp.drawText(tb, Qt.AlignCenter, "Home — Dolphin")
        for i, col in enumerate((mu, mu, an[1])):
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(col))
            qp.drawEllipse(QPointF(tb.right() - 18 - (2 - i) * 20, tb.center().y()), 6, 6)

        sb = QRectF(r.left(), tb.bottom(), r.width() * 0.3, r.height() - 32)
        qp.setFont(self._font(7.5, True))
        qp.setPen(QColor(mu))
        qp.drawText(QRectF(sb.left() + 14, sb.top() + 8, sb.width(), 18), Qt.AlignVCenter, "PLACES")
        qp.setFont(self._font(9))
        y = sb.top() + 30
        for i, name in enumerate(["Home", "Desktop", "Documents", "Downloads", "Music", "Pictures"]):
            if y + 26 > sb.bottom():
                break
            row = QRectF(sb.left() + 6, y, sb.width() - 12, 25)
            if i == 0:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(ac))
                qp.drawRoundedRect(row, 5, 5)
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(sel_fg if i == 0 else p["accent2"]))
            qp.drawRoundedRect(QRectF(row.left() + 8, row.center().y() - 5, 10, 10), 2, 2)
            qp.setPen(QColor(sel_fg if i == 0 else fg))
            qp.drawText(row.adjusted(26, 0, 0, 0), Qt.AlignVCenter, name)
            y += 27

        va = QRectF(sb.right(), tb.bottom(), r.width() - sb.width(), r.height() - 32)
        qp.fillRect(va, QColor(view))
        qp.setPen(QColor(mix(view, fg, 0.12)))
        qp.drawLine(QPointF(va.left(), va.top()), QPointF(va.left(), va.bottom()))
        qp.setFont(self._font(12, True))
        qp.setPen(QColor(fg))
        qp.drawText(QRectF(va.left() + 16, va.top() + 8, va.width(), 24), Qt.AlignVCenter, "Home")
        qp.setFont(self._font(8.5))
        qp.setPen(QColor(mu))
        qp.drawText(QRectF(va.left() + 16, va.top() + 30, va.width(), 18), Qt.AlignVCenter,
                    "4 folders · 3 files")
        files = [("Documents", True), ("Games", True), ("Music", True), ("Pictures", True),
                 ("notes.md", False), ("build.sh", False), ("wall.png", False)]
        y = va.top() + 54
        qp.setFont(self._font(9))
        bottom_ui = va.bottom() - 52
        for i, (name, folder) in enumerate(files):
            if y + 24 > bottom_ui:
                break
            row = QRectF(va.left() + 8, y, va.width() - 16, 23)
            if i == 2:
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor(mix(view, ac, 0.18)))
                qp.drawRoundedRect(row, 4, 4)
            elif i % 2:
                qp.fillRect(row, QColor(mix(view, fg, 0.03)))
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(ac if folder else mu))
            qp.drawRoundedRect(QRectF(row.left() + 8, row.center().y() - 6, 14, 12), 2, 2)
            qp.setPen(QColor(fg))
            qp.drawText(row.adjusted(32, 0, 0, 0), Qt.AlignVCenter, name)
            y += 24

        track = QRectF(va.left() + 16, va.bottom() - 44, va.width() * 0.42, 6)
        qp.setPen(Qt.NoPen)
        qp.setBrush(QColor(mix(view, fg, 0.12)))
        qp.drawRoundedRect(track, 3, 3)
        qp.setBrush(QColor(ac))
        qp.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * 0.62, 6), 3, 3)
        qp.setFont(self._font(9))
        for label, fill, txt, x in (("Cancel", sf, fg, va.right() - 176), ("Apply", ac, sel_fg, va.right() - 90)):
            btn = QRectF(x, va.bottom() - 36, 76, 26)
            qp.setPen(QPen(QColor(mix(fill, fg, 0.15)), 1))
            qp.setBrush(QColor(fill))
            qp.drawRoundedRect(btn, 5, 5)
            qp.setPen(QColor(txt))
            qp.drawText(btn, Qt.AlignCenter, label)
        qp.restore()
        qp.setPen(QPen(QColor(mix(bg, fg, 0.15)), 1))
        qp.setBrush(Qt.NoBrush)
        qp.drawRoundedRect(r, 9, 9)

    def draw_term(self, qp, r, p):
        bg, sf, fg, mu, ac = (p[k] for k in ("background", "surface", "foreground", "muted", "accent"))
        an = p["ansi"]
        qp.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        qp.setClipPath(clip)
        qp.fillRect(r, QColor(bg))

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSizeF(9.5)
        qp.setFont(mono)
        fm = QFontMetricsF(mono)
        for i, (label, fill, txt) in enumerate(((" 1  ~ ", ac, best_text(ac, p)), (" 2  cava ", sf, mu))):
            tab = QRectF(r.left() + i * 104, r.top(), 104, 24)
            qp.fillRect(tab, QColor(fill))
            qp.setPen(QColor(txt))
            qp.drawText(tab, Qt.AlignCenter, label.strip())

        lines = [
            [(an[2], "user@nobara"), (fg, ":"), (an[4], "~"), (fg, "$ ls")],
            [(an[4], "Documents  "), (an[4], "Music  "), (an[2], "build.sh  "), (fg, "notes.md  "),
             (an[5], "wall.png  "), (an[6], "link")],
            [(an[2], "user@nobara"), (fg, ":"), (an[4], "~"), (fg, "$ git status")],
            [(an[2], "  modified:   themeforge.py")],
            [(an[1], "  deleted:    old-theme.conf")],
            [(an[3], "warning: "), (fg, "2 files changed  "), (mu, "# comment")],
        ]
        x0, lh = r.left() + 12, fm.height() + 2
        y = r.top() + 24 + 10 + fm.ascent()
        for segs in lines:
            if y > r.bottom() - 70:
                break
            x = x0
            for col, txt in segs:
                qp.setPen(QColor(col))
                qp.drawText(QPointF(x, y), txt)
                x += fm.horizontalAdvance(txt)
            y += lh
        sw = (r.width() - 24) / 16
        top = y - fm.ascent() + 2
        for i, c in enumerate(an):
            qp.fillRect(QRectF(x0 + i * sw, top, sw - 3, 14), QColor(c))
        # cava
        ca = QRectF(r.left() + 12, top + 26, r.width() - 24, r.bottom() - 10 - (top + 26))
        if ca.height() > 16:
            n, gap = 36, 3
            bw = (ca.width() - gap * (n - 1)) / n
            grad = QLinearGradient(0, ca.bottom(), 0, ca.top())
            g = p["gradient"]
            if len(g) == 1:
                grad.setColorAt(0, QColor(g[0]))
                grad.setColorAt(1, QColor(g[0]))
            else:
                for i, c in enumerate(g):
                    grad.setColorAt(i / (len(g) - 1), QColor(c))
            brush = QBrush(grad)
            for i in range(n):
                v = (0.5 + 0.25 * math.sin(self.t * 3 + i * 0.45)
                     + 0.25 * math.sin(self.t * 5.3 - i * 0.8) * math.cos(self.t * 1.7 + i * 0.2))
                v *= 1 - 0.4 * abs(i / n - 0.3)
                h = max(2.0, clamp(v) * ca.height())
                qp.fillRect(QRectF(ca.left() + i * (bw + gap), ca.bottom() - h, bw, h), brush)
        qp.restore()
        qp.setPen(QPen(QColor(mix(bg, fg, 0.15)), 1))
        qp.setBrush(Qt.NoBrush)
        qp.drawRoundedRect(r, 9, 9)


# ── widget preview ─────────────────────────────────────────────────

class WidgetPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.w = None
        self.pal = None
        self.wall = None
        self.wall_path = None
        self.setMinimumSize(360, 420)
        t = QTimer(self)
        t.setInterval(1000)
        t.timeout.connect(self.update)
        t.start()

    def set_data(self, w, p, wallpaper):
        self.w, self.pal = w, p
        if wallpaper != self.wall_path:
            self.wall_path = wallpaper
            self.wall = QPixmap(wallpaper) if wallpaper and Path(wallpaper).exists() else None
        self.update()

    def font(self, size, bold=False):
        f = QFont(self.w["font"])
        f.setPointSizeF(max(1, size))
        f.setBold(bold)
        return f

    def row_h(self, row):
        base = QFontMetricsF(self.font(self.w["font_size"])).height()
        kind = row[0]
        if kind == "text":
            return QFontMetricsF(self.font(row[3], row[4])).height()
        if kind == "kv":
            return base
        if kind == "bar":
            return 12
        if kind == "graph":
            return 32
        if kind == "hr":
            return 9
        if kind == "space":
            return base * row[1]
        if kind == "mono":
            return QFontMetricsF(self.mono(row[2])).height()
        return 0

    @staticmethod
    def mono(size):
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        f.setPointSizeF(max(1, size))
        return f

    def paintEvent(self, e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p = self.pal
        if not p:
            return
        if self.wall and not self.wall.isNull():
            sc = self.wall.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            qp.drawPixmap(0, 0, sc, (sc.width() - r.width()) // 2, (sc.height() - r.height()) // 2,
                          r.width(), r.height())
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            g.setColorAt(0, QColor(mix(p["background"], "#000000", 0.3)))
            g.setColorAt(1, QColor(mix(p["surface"], p["accent"], 0.3)))
            qp.fillRect(r, g)
        if not self.w:
            qp.setPen(QColor(p["foreground"]))
            qp.drawText(r, Qt.AlignCenter, "Create or pick a widget")
            return
        w = self.w
        rows = [row for b in w["blocks"] for row in preview_rows(b, w, p)]
        heights = [self.row_h(row) for row in rows]
        pad, inner = w["padding"], w["width"]
        pw, ph = inner + 2 * pad, max(sum(heights), 10) + 2 * pad
        scale = min(1.0, (r.width() - 24) / pw, (r.height() - 24) / ph)
        vert, horiz = w["alignment"].split("_")
        m = 12
        px = {"left": m, "middle": (r.width() - pw * scale) / 2, "right": r.width() - m - pw * scale}[horiz]
        py = {"top": m, "middle": (r.height() - ph * scale) / 2, "bottom": r.height() - m - ph * scale}[vert]
        qp.save()
        qp.translate(px, py)
        qp.scale(scale, scale)
        bgc = QColor(p["background"])
        bgc.setAlpha(round(w["opacity"] * 2.55))
        qp.fillRect(QRectF(0, 0, pw, ph), bgc)
        if w["opacity"] == 0:
            qp.setPen(QPen(QColor(mix(p["foreground"], p["background"], 0.5)), 1, Qt.DashLine))
            qp.setBrush(Qt.NoBrush)
            qp.drawRect(QRectF(0, 0, pw, ph))
        y = pad
        for row, h in zip(rows, heights):
            self.draw_row(qp, row, QRectF(pad, y, inner, h))
            y += h
        qp.restore()

    def draw_row(self, qp, row, rect):
        p, w = self.pal, self.w
        kind = row[0]
        align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
        if kind == "text":
            _, text, role, size, bold, al = row
            qp.setFont(self.font(size, bold))
            qp.setPen(QColor(role_color(p, role)))
            qp.drawText(rect, align.get(al, Qt.AlignLeft) | Qt.AlignVCenter, text)
        elif kind == "mono":
            _, segs, size, al = row
            f = self.mono(size)
            fm = QFontMetricsF(f)
            qp.setFont(f)
            total = sum(fm.horizontalAdvance(t) for t, _ in segs)
            x = {"center": rect.left() + (rect.width() - total) / 2,
                 "right": rect.right() - total}.get(al, rect.left())
            y = rect.top() + fm.ascent()
            for text, role in segs:
                qp.setPen(QColor(role_color(p, role)))
                qp.drawText(QPointF(x, y), text)
                x += fm.horizontalAdvance(text)
        elif kind == "kv":
            _, label, value, lr, vr = row
            qp.setFont(self.font(w["font_size"]))
            qp.setPen(QColor(role_color(p, lr)))
            qp.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, label)
            qp.setPen(QColor(role_color(p, vr)))
            qp.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, value)
        elif kind == "bar":
            _, frac, role = row
            col = role_color(p, role)
            track = QRectF(rect.left(), rect.top() + 3, rect.width(), 6)
            qp.fillRect(track, QColor(mix(col, p["background"], 0.75)))
            qp.fillRect(QRectF(track.left(), track.top(), track.width() * frac, 6), QColor(col))
        elif kind == "graph":
            _, seed, role = row
            rnd = random.Random(seed)
            n, vals, v = 48, [], 0.3
            for _ in range(n):
                v = clamp(v + rnd.uniform(-0.18, 0.18), 0.05, 0.95)
                vals.append(v)
            gr = QRectF(rect.left(), rect.top() + 2, rect.width(), rect.height() - 4)
            path = QPainterPath(QPointF(gr.left(), gr.bottom()))
            for i, v in enumerate(vals):
                path.lineTo(gr.left() + gr.width() * i / (n - 1), gr.bottom() - v * gr.height())
            path.lineTo(gr.right(), gr.bottom())
            path.closeSubpath()
            grad = QLinearGradient(0, gr.bottom(), 0, gr.top())
            grad.setColorAt(0, QColor(role_color(p, role)))
            grad.setColorAt(1, QColor(p["accent"] if role == "accent2" else p["accent2"]))
            qp.fillPath(path, QBrush(grad))
        elif kind == "hr":
            qp.setPen(QPen(QColor(role_color(p, row[1])), 1))
            y = rect.center().y()
            qp.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))


# ── Colors tab ─────────────────────────────────────────────────────

class ColorsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        outer = QHBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(480)
        panel = QWidget()
        col = QVBoxLayout(panel)
        col.setContentsMargins(4, 4, 12, 4)
        col.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        gb = QGroupBox("Start from a wallpaper")
        g = QGridLayout(gb)
        self.thumb = QLabel("No image yet")
        self.thumb.setObjectName("thumb")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedSize(208, 117)
        g.addWidget(self.thumb, 0, 0, 4, 1)
        b_choose = QPushButton("Choose image…")
        b_choose.clicked.connect(self.choose_wallpaper)
        b_dark = QPushButton("Generate dark theme")
        b_dark.clicked.connect(lambda *_: self.generate(False))
        b_light = QPushButton("Generate light theme")
        b_light.clicked.connect(lambda *_: self.generate(True))
        g.addWidget(b_choose, 0, 1)
        g.addWidget(b_dark, 1, 1)
        g.addWidget(b_light, 2, 1)
        self.set_wall = QCheckBox("Also set it as my wallpaper")
        self.set_wall.toggled.connect(self.toggle_wall)
        g.addWidget(self.set_wall, 3, 1)
        col.addWidget(gb)

        gb = QGroupBox("Interface")
        g = QGridLayout(gb)
        self.role_btns = {}
        for i, (key, label) in enumerate(ROLES):
            btn = SwatchButton()
            btn.colorPicked.connect(lambda c, k=key: self.win.edit_palette(k, c))
            self.role_btns[key] = btn
            g.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g.addWidget(btn, i // 2, (i % 2) * 2 + 1)
        col.addWidget(gb)

        gb = QGroupBox("Terminal colors")
        g = QGridLayout(gb)
        g.setHorizontalSpacing(4)
        self.ansi_btns = []
        for j, name in enumerate(ANSI_NAMES):
            lbl = QLabel(name[:3])
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignCenter)
            g.addWidget(lbl, 0, j + 1)
        for row, rname in enumerate(("Normal", "Bright")):
            lbl = QLabel(rname)
            lbl.setObjectName("muted")
            g.addWidget(lbl, row + 1, 0)
            for j in range(8):
                idx = row * 8 + j
                btn = SwatchButton(compact=True)
                btn.colorPicked.connect(lambda c, i=idx: self.win.edit_ansi(i, c))
                self.ansi_btns.append(btn)
                g.addWidget(btn, row + 1, j + 1)
        col.addWidget(gb)

        gb = QGroupBox("cava gradient  (bottom → top)")
        v = QVBoxLayout(gb)
        self.grad_row = QHBoxLayout()
        self.grad_row.setSpacing(4)
        v.addLayout(self.grad_row)
        row = QHBoxLayout()
        b_add = QPushButton("+ Add stop")
        b_add.clicked.connect(self.add_stop)
        b_rm = QPushButton("− Remove last")
        b_rm.clicked.connect(self.remove_stop)
        b_reset = QPushButton("Match palette")
        b_reset.clicked.connect(lambda *_: self.win.set_gradient(default_gradient(self.win.pal)))
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addWidget(b_reset)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(hint_label("Up to 8 colors. One color = solid bars."))
        col.addWidget(gb)
        col.addStretch()
        scroll.setWidget(panel)
        outer.addWidget(scroll)

        self.preview = PalettePreview()
        outer.addWidget(self.preview, 1)

    def refresh(self):
        p = self.win.pal
        for key, btn in self.role_btns.items():
            btn.set_color(p[key])
        for i, btn in enumerate(self.ansi_btns):
            btn.set_color(p["ansi"][i])
        while self.grad_row.count():
            item = self.grad_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, c in enumerate(p["gradient"]):
            btn = SwatchButton(c, compact=True)
            btn.colorPicked.connect(lambda c2, i=i: self.win.edit_gradient(i, c2))
            self.grad_row.addWidget(btn)
        self.grad_row.addStretch()
        self.set_wall.blockSignals(True)
        self.set_wall.setChecked(bool(self.win.settings["targets"].get("wallpaper")))
        self.set_wall.blockSignals(False)
        self.update_thumb()
        self.preview.set_palette(p)

    def update_thumb(self):
        wp = self.win.settings.get("wallpaper")
        if wp and Path(wp).exists():
            pm = QPixmap(wp).scaled(self.thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.thumb.setPixmap(pm.copy((pm.width() - 208) // 2, (pm.height() - 117) // 2, 208, 117))
        else:
            self.thumb.setText("No image yet")

    def toggle_wall(self, on):
        self.win.settings["targets"]["wallpaper"] = on
        self.win.targets_tab.refresh()
        self.win.schedule_save()

    def choose_wallpaper(self):
        start = HOME / "Pictures"
        path, _ = QFileDialog.getOpenFileName(self, "Choose a wallpaper", str(start if start.exists() else HOME),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return False
        self.win.settings["wallpaper"] = path
        self.update_thumb()
        self.win.widgets_tab.refresh_preview()
        self.generate(not is_dark(self.win.pal["background"]))
        return True

    def generate(self, light):
        wp = self.win.settings.get("wallpaper")
        if not wp or not Path(wp).exists():
            self.choose_wallpaper()
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = palette_from_wallpaper(wp, light)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "ThemeForge", f"Couldn't read colors from that image:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.win.set_palette(p)

    def add_stop(self):
        g = list(self.win.pal["gradient"])
        if len(g) < 8:
            g.append(mix(g[-1], self.win.pal["accent"], 0.5) if len(g) else self.win.pal["accent"])
            self.win.set_gradient(g)

    def remove_stop(self):
        g = list(self.win.pal["gradient"])
        if len(g) > 1:
            self.win.set_gradient(g[:-1])


# ── Widgets tab ────────────────────────────────────────────────────

class WidgetsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cur = None
        self.cur_block = None
        self.loading = False
        self.write_timer = QTimer(self)
        self.write_timer.setSingleShot(True)
        self.write_timer.setInterval(400)
        self.write_timer.timeout.connect(self.write_current)

        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)

        # left: widget list + external conky files
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(section_label("Your widgets"))
        self.wlist = QListWidget()
        self.wlist.currentRowChanged.connect(self.select_widget)
        lv.addWidget(self.wlist, 3)
        row = QHBoxLayout()
        b_new = QToolButton()
        b_new.setText("New ▾")
        b_new.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b_new)
        for key, label in WIDGET_TEMPLATES:
            m.addAction(label.replace("&", "&&")).triggered.connect(lambda *_, k=key: self.add_widget(k))
        b_new.setMenu(m)
        b_dup = QPushButton("Duplicate")
        b_dup.clicked.connect(self.dup_widget)
        b_del = QPushButton("Delete")
        b_del.clicked.connect(self.del_widget)
        for b in (b_new, b_dup, b_del):
            row.addWidget(b)
        lv.addLayout(row)

        lv.addWidget(section_label("Existing conky configs"))
        lv.addWidget(hint_label("Recolor swaps the hex values of default_color, own_window_colour "
                                "and color0–9 for palette colors (0 text, 1 accent, 2 accent 2, 3 muted…)."))
        self.elist = QListWidget()
        self.elist.currentRowChanged.connect(self.select_ext)
        lv.addWidget(self.elist, 2)
        row = QHBoxLayout()
        b_add = QPushButton("Add…")
        b_add.clicked.connect(self.add_ext)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(self.rm_ext)
        self.ext_toggle = QPushButton("Start")
        self.ext_toggle.clicked.connect(self.toggle_ext)
        for b in (b_add, b_rm, self.ext_toggle):
            row.addWidget(b)
        lv.addLayout(row)
        self.ext_recolor = QCheckBox("Recolor on Apply")
        self.ext_recolor.toggled.connect(lambda v: self.set_ext("recolor", v))
        self.ext_auto = QCheckBox("Start at login")
        self.ext_auto.toggled.connect(lambda v: self.set_ext("autostart", v))
        lv.addWidget(self.ext_recolor)
        lv.addWidget(self.ext_auto)
        split.addWidget(left)

        # middle: editor
        mid_scroll = QScrollArea()
        mid_scroll.setWidgetResizable(True)
        mid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(4, 0, 12, 0)
        mv.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        gb = QGroupBox("Widget")
        f = QFormLayout(gb)
        self.f_name = QLineEdit()
        self.f_name.textEdited.connect(lambda v: self.set_field("name", v))
        self.f_align = QComboBox()
        for k, label in ALIGNMENTS:
            self.f_align.addItem(label, k)
        self.f_align.currentIndexChanged.connect(lambda i: self.set_field("alignment", self.f_align.itemData(i)))
        self.f_gapx = spin(-4000, 4000, " px")
        self.f_gapx.valueChanged.connect(lambda v: self.set_field("gap_x", v))
        self.f_gapy = spin(-4000, 4000, " px")
        self.f_gapy.valueChanged.connect(lambda v: self.set_field("gap_y", v))
        self.f_width = spin(60, 2000, " px")
        self.f_width.valueChanged.connect(lambda v: self.set_field("width", v))
        self.f_font = QFontComboBox()
        self.f_font.currentFontChanged.connect(lambda fnt: self.set_field("font", fnt.family()))
        self.f_fsize = spin(6, 48, " pt")
        self.f_fsize.valueChanged.connect(lambda v: self.set_field("font_size", v))
        self.f_opacity = spin(0, 100, " %")
        self.f_opacity.valueChanged.connect(lambda v: self.set_field("opacity", v))
        self.f_pad = spin(0, 100, " px")
        self.f_pad.valueChanged.connect(lambda v: self.set_field("padding", v))
        self.f_interval = QDoubleSpinBox()
        self.f_interval.setRange(0.5, 60)
        self.f_interval.setSingleStep(0.5)
        self.f_interval.setSuffix(" s")
        self.f_interval.valueChanged.connect(lambda v: self.set_field("interval", v))
        self.f_auto = QCheckBox("Start this widget when I log in")
        self.f_auto.toggled.connect(self.set_autostart)
        gap_row = QHBoxLayout()
        gap_row.addWidget(self.f_gapx)
        gap_row.addWidget(QLabel("↕"))
        gap_row.addWidget(self.f_gapy)
        f.addRow("Name", self.f_name)
        f.addRow("Position", self.f_align)
        f.addRow("Offset  ↔", gap_row)
        f.addRow("Width", self.f_width)
        f.addRow("Font", self.f_font)
        f.addRow("Base size", self.f_fsize)
        f.addRow("Background", self.f_opacity)
        f.addRow("Padding", self.f_pad)
        f.addRow("Update every", self.f_interval)
        f.addRow("", self.f_auto)
        mv.addWidget(gb)

        gb = QGroupBox("Blocks  (top to bottom)")
        bv = QVBoxLayout(gb)
        self.blist = QListWidget()
        self.blist.setMinimumHeight(190)
        self.blist.currentRowChanged.connect(self.select_block)
        bv.addWidget(self.blist)
        row = QHBoxLayout()
        b_addb = QToolButton()
        b_addb.setText("Add block ▾")
        b_addb.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b_addb)
        for key, (title, _f) in BLOCK_TYPES.items():
            m.addAction(title.replace("&", "&&")).triggered.connect(lambda *_, k=key: self.add_block(k))
        b_addb.setMenu(m)
        row.addWidget(b_addb)
        for label, fn in (("↑", lambda *_: self.move_block(-1)), ("↓", lambda *_: self.move_block(1)),
                          ("Remove", self.remove_block)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        bv.addLayout(row)
        mv.addWidget(gb)

        gb = QGroupBox("Block settings")
        self.bform = QFormLayout(gb)
        mv.addWidget(gb)
        mv.addStretch()
        mid_scroll.setWidget(mid)
        split.addWidget(mid_scroll)

        # right: preview + run controls
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        self.preview = WidgetPreview()
        rv.addWidget(self.preview, 1)
        rv.addWidget(hint_label("Preview uses sample values. Run it to see the real widget — "
                                "while it's running, your edits show up on the desktop within a second."))
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run on desktop")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run_widget)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_widget)
        b_cfg = QPushButton("View conky config")
        b_cfg.clicked.connect(self.view_config)
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(b_cfg)
        row.addStretch()
        self.status = QLabel()
        row.addWidget(self.status)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([270, 430, 560])

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(3000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

    # ── model helpers
    @property
    def widgets(self):
        return self.win.settings["widgets"]

    @property
    def externals(self):
        return self.win.settings.setdefault("external_conky", [])

    def refresh(self):
        row = self.wlist.currentRow()
        self.wlist.blockSignals(True)
        self.wlist.clear()
        for w in self.widgets:
            self.wlist.addItem(w["name"])
        self.wlist.blockSignals(False)
        self.elist.blockSignals(True)
        self.elist.clear()
        for e in self.externals:
            self.elist.addItem(Path(e["path"]).name)
        self.elist.blockSignals(False)
        if self.widgets:
            self.wlist.setCurrentRow(min(max(row, 0), len(self.widgets) - 1))
            self.select_widget(self.wlist.currentRow())
        else:
            self.select_widget(-1)
        self.select_ext(self.elist.currentRow())
        self.refresh_status()

    def refresh_preview(self):
        self.preview.set_data(self.cur, self.win.pal, self.win.settings.get("wallpaper"))

    def changed(self):
        self.refresh_preview()
        self.write_timer.start()
        self.win.schedule_save()

    def write_current(self):
        if self.cur:
            write_widget(self.cur, self.win.pal)

    # ── widget list
    def select_widget(self, row):
        self.cur = self.widgets[row] if 0 <= row < len(self.widgets) else None
        self.loading = True
        w = self.cur
        for wdg in (self.f_name, self.f_align, self.f_gapx, self.f_gapy, self.f_width, self.f_font,
                    self.f_fsize, self.f_opacity, self.f_pad, self.f_interval, self.f_auto):
            wdg.setEnabled(w is not None)
        if w:
            self.f_name.setText(w["name"])
            self.f_align.setCurrentIndex(max(0, self.f_align.findData(w["alignment"])))
            self.f_gapx.setValue(w["gap_x"])
            self.f_gapy.setValue(w["gap_y"])
            self.f_width.setValue(w["width"])
            self.f_font.setCurrentFont(QFont(w["font"]))
            self.f_fsize.setValue(w["font_size"])
            self.f_opacity.setValue(w["opacity"])
            self.f_pad.setValue(w["padding"])
            self.f_interval.setValue(w["interval"])
            self.f_auto.setChecked(w["autostart"])
        self.loading = False
        self.refresh_blocks(0)
        self.refresh_preview()
        self.refresh_status()

    def set_field(self, key, val):
        if self.loading or not self.cur:
            return
        self.cur[key] = val
        if key == "name":
            item = self.wlist.currentItem()
            if item:
                item.setText(val)
        self.changed()

    def set_autostart(self, on):
        if self.loading or not self.cur:
            return
        self.cur["autostart"] = on
        update_autostart(self.win.settings)
        self.changed()

    def add_widget(self, kind):
        w = widget_template(kind)
        self.widgets.append(w)
        write_widget(w, self.win.pal)
        self.refresh()
        self.wlist.setCurrentRow(len(self.widgets) - 1)
        self.win.schedule_save()

    def dup_widget(self):
        if not self.cur:
            return
        w = copy.deepcopy(self.cur)
        w["id"] = uuid.uuid4().hex[:8]
        w["name"] += " copy"
        w["gap_y"] += 40
        self.widgets.append(w)
        write_widget(w, self.win.pal)
        self.refresh()
        self.wlist.setCurrentRow(len(self.widgets) - 1)
        self.win.schedule_save()

    def del_widget(self):
        if not self.cur:
            return
        if QMessageBox.question(self, "Delete widget", f"Delete “{self.cur['name']}”?") != QMessageBox.Yes:
            return
        path = widget_path(self.cur)
        stop_conky(path)
        if path.exists():
            path.unlink()
        self.widgets.remove(self.cur)
        self.cur = None
        update_autostart(self.win.settings)
        self.refresh()
        self.win.schedule_save()

    # ── blocks
    def refresh_blocks(self, select=None):
        self.blist.blockSignals(True)
        self.blist.clear()
        if self.cur:
            for b in self.cur["blocks"]:
                self.blist.addItem(block_summary(b))
        self.blist.blockSignals(False)
        n = self.blist.count()
        if n and select is not None:
            self.blist.setCurrentRow(max(0, min(select, n - 1)))
        self.select_block(self.blist.currentRow())

    def select_block(self, row):
        self.cur_block = row if self.cur and 0 <= row < len(self.cur["blocks"]) else None
        self.build_block_form()

    def build_block_form(self):
        while self.bform.rowCount():
            self.bform.removeRow(0)
        if self.cur_block is None:
            self.bform.addRow(hint_label("Add a block or pick one from the list to edit it."))
            return
        b = self.cur["blocks"][self.cur_block]
        title, fields = BLOCK_TYPES[b["type"]]
        head = QLabel(title)
        head.setStyleSheet("font-weight: bold;")
        self.bform.addRow(head)
        for key, kind, label, default, opts in fields:
            val = b.get(key, default)
            if kind == "text":
                wdg = QLineEdit(str(val))
                wdg.textEdited.connect(lambda v, k=key: self.set_block(k, v))
            elif kind == "int":
                wdg = spin(*opts)
                wdg.setValue(int(val))
                wdg.valueChanged.connect(lambda v, k=key: self.set_block(k, v))
            elif kind == "bool":
                wdg = QCheckBox()
                wdg.setChecked(bool(val))
                wdg.toggled.connect(lambda v, k=key: self.set_block(k, v))
            else:
                wdg = QComboBox()
                if kind == "role":
                    for r in COLOR_SLOTS:
                        wdg.addItem(color_icon(role_color(self.win.pal, r)), ROLE_NAMES[r], r)
                elif kind == "align":
                    for k2, l2 in TEXT_ALIGN:
                        wdg.addItem(l2, k2)
                else:
                    for o in opts:
                        wdg.addItem({"us": "US (°F)", "metric": "Metric (°C)", "c": "°C", "f": "°F"}.get(o, o.capitalize()), o)
                wdg.setCurrentIndex(max(0, wdg.findData(val)))
                wdg.currentIndexChanged.connect(lambda i, k=key, w=wdg: self.set_block(k, w.itemData(i)))
            self.bform.addRow(label, wdg)
        tips = {"text": "Conky variables work here, e.g. ${kernel} or ${nodename}.",
                "clock": "strftime codes: %H:%M 24-hour, %I:%M %p 12-hour, %S seconds.",
                "date": "strftime codes: %A weekday, %d day, %B month, %Y year.",
                "command": "Runs through the shell. Avoid { } braces — conky treats them specially.",
                "nowplaying": "Uses playerctl, so it works with Spotify, browsers, mpv and most players.",
                "weather": "From wttr.in. Use a city name, airport code, or leave blank for your IP location."}
        if b["type"] in tips:
            self.bform.addRow(hint_label(tips[b["type"]]))

    def set_block(self, key, val):
        if self.cur_block is None:
            return
        b = self.cur["blocks"][self.cur_block]
        b[key] = val
        item = self.blist.item(self.cur_block)
        if item:
            item.setText(block_summary(b))
        self.changed()

    def add_block(self, btype):
        if not self.cur:
            return
        pos = (self.cur_block + 1) if self.cur_block is not None else len(self.cur["blocks"])
        self.cur["blocks"].insert(pos, new_block(btype))
        self.refresh_blocks(pos)
        self.changed()

    def move_block(self, d):
        i = self.cur_block
        if i is None:
            return
        j = i + d
        bl = self.cur["blocks"]
        if 0 <= j < len(bl):
            bl[i], bl[j] = bl[j], bl[i]
            self.refresh_blocks(j)
            self.changed()

    def remove_block(self):
        if self.cur_block is None:
            return
        del self.cur["blocks"][self.cur_block]
        self.refresh_blocks(self.cur_block)
        self.changed()

    # ── running
    def run_widget(self):
        if not self.cur:
            return
        if not shutil.which("conky"):
            QMessageBox.information(self, "conky needed", "Widgets are drawn by conky.\n\n"
                                    "Install it with:\n    sudo dnf install conky playerctl")
            return
        path = write_widget(self.cur, self.win.pal)
        if not conky_pids(path):
            start_conky(path)
        QTimer.singleShot(900, self.refresh_status)

    def stop_widget(self):
        if self.cur:
            stop_conky(widget_path(self.cur))
            QTimer.singleShot(500, self.refresh_status)

    def view_config(self):
        if not self.cur:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"conky config — {self.cur['name']}")
        dlg.resize(760, 620)
        v = QVBoxLayout(dlg)
        v.addWidget(hint_label(str(widget_path(self.cur))))
        txt = QPlainTextEdit(conky_config(self.cur, self.win.pal))
        txt.setReadOnly(True)
        txt.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        v.addWidget(txt)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()

    def refresh_status(self):
        if not self.isVisible():
            return
        procs = conky_procs()
        for i, w in enumerate(self.widgets):
            item = self.wlist.item(i)
            if item:
                item.setText(("●  " if conky_pids(widget_path(w), procs) else "") + w["name"])
        for i, e in enumerate(self.externals):
            item = self.elist.item(i)
            if item:
                item.setText(("●  " if conky_pids(e["path"], procs) else "") + Path(e["path"]).name)
        running = bool(self.cur and conky_pids(widget_path(self.cur), procs))
        self.status.setText("● running" if running else "○ not running")
        self.status.setStyleSheet(f"color: {self.win.pal['ansi'][2] if running else self.win.pal['muted']};")
        e = self.cur_ext()
        self.ext_toggle.setText("Stop" if e and conky_pids(e["path"], procs) else "Start")

    # ── external conky files
    def cur_ext(self):
        i = self.elist.currentRow()
        return self.externals[i] if 0 <= i < len(self.externals) else None

    def select_ext(self, _row):
        e = self.cur_ext()
        for wdg in (self.ext_recolor, self.ext_auto, self.ext_toggle):
            wdg.setEnabled(e is not None)
        self.ext_recolor.blockSignals(True)
        self.ext_auto.blockSignals(True)
        self.ext_recolor.setChecked(bool(e and e.get("recolor")))
        self.ext_auto.setChecked(bool(e and e.get("autostart")))
        self.ext_recolor.blockSignals(False)
        self.ext_auto.blockSignals(False)
        if e:
            self.elist.setToolTip(e["path"])
        self.refresh_status()

    def set_ext(self, key, val):
        e = self.cur_ext()
        if e:
            e[key] = val
            if key == "autostart":
                update_autostart(self.win.settings)
            self.win.schedule_save()

    def add_ext(self):
        start = HOME / ".config" / "conky"
        path, _ = QFileDialog.getOpenFileName(self, "Add a conky config", str(start if start.exists() else HOME),
                                              "All files (*)")
        if path and not any(e["path"] == path for e in self.externals):
            self.externals.append({"path": path, "recolor": True, "autostart": False})
            self.refresh()
            self.elist.setCurrentRow(len(self.externals) - 1)
            self.win.schedule_save()

    def rm_ext(self):
        e = self.cur_ext()
        if e:
            self.externals.remove(e)
            update_autostart(self.win.settings)
            self.refresh()
            self.win.schedule_save()

    def toggle_ext(self):
        e = self.cur_ext()
        if not e:
            return
        if conky_pids(e["path"]):
            stop_conky(e["path"])
        else:
            start_conky(e["path"])
        QTimer.singleShot(800, self.refresh_status)


# ── Visualizers tab ────────────────────────────────────────────────

class VisualizerPreview(QWidget):
    """A miniature of your screen with the visualizer placed on it, animated with fake audio."""

    def __init__(self):
        super().__init__()
        self.v = None
        self.pal = None
        self.wall = None
        self.wall_path = None
        self.panels = []
        self.t = 0.0
        self.setMinimumSize(380, 260)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)

    def set_data(self, v, p, wallpaper, panels=None):
        self.v, self.pal = v, p
        self.panels = panels or []
        if wallpaper != self.wall_path:
            self.wall_path = wallpaper
            self.wall = QPixmap(wallpaper) if wallpaper and Path(wallpaper).exists() else None
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def tick(self):
        self.t += 0.033
        self.update()

    def screen_geom(self):
        scr = QGuiApplication.primaryScreen()
        if self.v:
            scr = next((s for s in QGuiApplication.screens() if s.name() == self.v["screen"]), scr)
        g = scr.geometry() if scr else None
        return QRectF(0, 0, g.width(), g.height()) if g and g.width() > 0 else QRectF(0, 0, 1920, 1080)

    def paintEvent(self, e):
        p = self.pal
        if not p:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor(mix(p["background"], "#000000", 0.35)))
        sg = self.screen_geom()
        k = min((self.width() - 24) / sg.width(), (self.height() - 24) / sg.height())
        sr = QRectF((self.width() - sg.width() * k) / 2, (self.height() - sg.height() * k) / 2,
                    sg.width() * k, sg.height() * k)
        if self.wall and not self.wall.isNull():
            pm = self.wall.scaled(sr.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            qp.drawPixmap(sr.topLeft(), pm, QRectF((pm.width() - sr.width()) / 2,
                                                   (pm.height() - sr.height()) / 2, sr.width(), sr.height()))
        else:
            g = QLinearGradient(sr.topLeft(), sr.bottomRight())
            g.setColorAt(0, QColor(mix(p["background"], "#000000", 0.2)))
            g.setColorAt(1, QColor(mix(p["surface"], p["accent"], 0.25)))
            qp.fillRect(sr, g)
        qp.setPen(QPen(QColor(mix(p["foreground"], p["background"], 0.6)), 1))
        qp.setBrush(Qt.NoBrush)
        qp.drawRect(sr)
        if not self.v:
            qp.setPen(QColor(p["foreground"]))
            qp.drawText(sr, Qt.AlignCenter, "Create or pick a visualizer")
            return
        panels = self.panels
        g = vis_geometry(self.v, sg, panels)
        vr = QRectF(sr.left() + g.left() * k, sr.top() + g.top() * k, g.width() * k, g.height() * k)
        wrapped = wrapped_panel(self.v, panels)
        if wrapped is not None:
            n_items = panel_item_count(wrapped)
            pr = panel_rect(wrapped, sg, n_items)
            qp.save()
            qp.translate(sr.left(), sr.top())
            qp.scale(k, k)
            paint_panel(qp, pr.topLeft(), wrapped, p, {"items": [{"name": "", "path": str(i)}
                                                                  for i in range(n_items)],
                                                       "np": {"status": "Playing", "title": "Song title",
                                                              "artist": "Artist", "length": 200,
                                                              "position": 80}})
            qp.restore()
        else:
            qp.setPen(QPen(QColor(mix(p["foreground"], p["background"], 0.4)), 1, Qt.DotLine))
            qp.drawRect(vr)
        n = vis_bar_count(self.v)
        if wrapped is not None or self.v["style"] == "frame":
            qp.save()
            qp.translate(vr.left(), vr.top())
            qp.scale(k, k)
            paint_visualizer(qp, QRectF(0, 0, g.width(), g.height()), fake_spectrum(n, self.t, self.v["stereo"]),
                             self.v, p)
            qp.restore()
        else:
            paint_visualizer(qp, vr, fake_spectrum(n, self.t, self.v["stereo"]), self.v, p)
        qp.end()


class VisualizersTab(QWidget):
    FIELDS = [  # key, kind, label, options
        ("Look", [
            ("name", "text", "Name", None),
            ("style", "combo", "Style", VIS_STYLES),
            ("color", "combo", "Colors", VIS_COLORS),
            ("bars", "int", "Bars", (4, 256, "")),
            ("gap", "int", "Gap between bars", (0, 90, " %")),
            ("rounded", "bool", "Rounded ends", None),
            ("stereo", "bool", "Stereo - bass in the middle", None),
            ("flip", "bool", "Hang from the top", None),
            ("glow", "bool", "Glow with the bass", None),
            ("opacity", "int", "Opacity", (5, 100, " %")),
            ("smoothing", "int", "Smoothing", (0, 100, " %")),
            ("framerate", "int", "Frame rate", (10, 144, " fps")),
        ]),
        ("Placement", [
            ("wrap", "panel", "Wrap around", None),
            ("depth", "int", "Frame bar length", (6, 300, " px")),
            ("alignment", "combo", "Position", ALIGNMENTS),
            ("gap_x", "int", "Offset  ↔", (-8000, 8000, " px")),
            ("gap_y", "int", "Offset  ↕", (-8000, 8000, " px")),
            ("width", "int", "Width", (0, 8000, " px")),
            ("height", "int", "Height", (20, 4000, " px")),
            ("screen", "screen", "Screen", None),
            ("x11", "bool", "Pin to exact position (runs through XWayland)", None),
            ("autostart", "bool", "Start when I log in", None),
        ]),
    ]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cur = None
        self.loading = False
        self.inputs = {}
        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(section_label("Your visualizers"))
        self.vlist = QListWidget()
        self.vlist.currentRowChanged.connect(self.select)
        lv.addWidget(self.vlist, 1)
        row = QHBoxLayout()
        b_new = QToolButton()
        b_new.setText("New ▾")
        b_new.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b_new)
        for key, label in VIS_TEMPLATES:
            m.addAction(label.replace("&", "&&")).triggered.connect(lambda *_, k=key: self.add(k))
        b_new.setMenu(m)
        b_dup = QPushButton("Duplicate")
        b_dup.clicked.connect(self.duplicate)
        b_del = QPushButton("Delete")
        b_del.clicked.connect(self.delete)
        for b in (b_new, b_dup, b_del):
            row.addWidget(b)
        lv.addLayout(row)
        lv.addWidget(hint_label("Each visualizer is its own click-through window on your desktop, "
                                "drawn by ThemeForge from cava's audio data. Run as many as you like."))
        split.addWidget(left)

        mid_scroll = QScrollArea()
        mid_scroll.setWidgetResizable(True)
        mid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(4, 0, 12, 0)
        mv.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        for title, fields in self.FIELDS:
            gb = QGroupBox(title)
            f = QFormLayout(gb)
            for key, kind, label, opts in fields:
                wdg = self.make_input(key, kind, opts)
                if kind == "bool":
                    wdg.setText(label)
                    f.addRow("", wdg)
                else:
                    f.addRow(label, wdg)
                self.inputs[key] = wdg
            mv.addWidget(gb)
        mv.addStretch()
        mid_scroll.setWidget(mid)
        split.addWidget(mid_scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        self.preview = VisualizerPreview()
        rv.addWidget(self.preview, 1)
        rv.addWidget(hint_label("Preview uses fake audio. While a visualizer runs, changes here reach it "
                                "within a second; its colors follow your theme each time you Apply."))
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run on desktop")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run)
        b_stop = QPushButton("Stop")
        b_stop.clicked.connect(self.stop)
        b_all = QPushButton("Stop all")
        b_all.clicked.connect(self.stop_all)
        for b in (self.run_btn, b_stop, b_all):
            row.addWidget(b)
        row.addStretch()
        self.status = QLabel()
        row.addWidget(self.status)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([260, 420, 580])

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(3000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

    @property
    def items(self):
        return self.win.settings.setdefault("visualizers", [])

    def make_input(self, key, kind, opts):
        if kind == "text":
            w = QLineEdit()
            w.textEdited.connect(lambda val: self.set_field(key, val))
        elif kind == "int":
            w = spin(opts[0], opts[1], opts[2])
            if key == "width":
                w.setSpecialValueText("Full width")
            w.valueChanged.connect(lambda val: self.set_field(key, val))
        elif kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda val: self.set_field(key, val))
        else:
            w = QComboBox()
            if kind == "panel":
                w.addItem("Nothing - place it myself", "")
            elif kind == "screen":
                w.addItem("Primary screen", "")
                for s in QGuiApplication.screens():
                    w.addItem(f"{s.name()}  ({s.geometry().width()}×{s.geometry().height()})", s.name())
            else:
                for data, label in opts:
                    w.addItem(label, data)
            w.currentIndexChanged.connect(lambda i, box=w: self.set_field(key, box.itemData(i)))
        return w

    def refresh(self):
        row = self.vlist.currentRow()
        self.vlist.blockSignals(True)
        self.vlist.clear()
        for v in self.items:
            self.vlist.addItem(v["name"])
        self.vlist.blockSignals(False)
        if self.items:
            self.vlist.setCurrentRow(min(max(row, 0), len(self.items) - 1))
        self.select(self.vlist.currentRow())

    def refresh_preview(self):
        self.preview.set_data(self.cur, self.win.pal, self.win.settings.get("wallpaper"),
                              self.win.settings.get("panels"))

    def fill_panel_combo(self):
        box = self.inputs["wrap"]
        box.blockSignals(True)
        box.clear()
        box.addItem("Nothing - place it myself", "")
        for x in self.win.settings.get("panels", []):
            box.addItem(f"{x['name']}  ({dict(PANEL_KINDS)[x['kind']].lower()})", x["id"])
        box.blockSignals(False)

    def update_enabled(self):
        if not self.cur:
            return
        wrapped = bool(self.cur.get("wrap"))
        for key in ("alignment", "gap_x", "gap_y", "width", "height", "screen"):
            self.inputs[key].setEnabled(not wrapped)
        self.inputs["depth"].setEnabled(wrapped or self.cur["style"] == "frame")

    def select(self, row):
        self.cur = self.items[row] if 0 <= row < len(self.items) else None
        self.fill_panel_combo()
        self.loading = True
        for key, w in self.inputs.items():
            w.setEnabled(self.cur is not None)
            if not self.cur:
                continue
            val = self.cur[key]
            if isinstance(w, QLineEdit):
                w.setText(val)
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            else:
                idx = w.findData(val)
                if idx < 0 and key == "screen":
                    w.addItem(f"{val} (not connected)", val)
                    idx = w.count() - 1
                w.setCurrentIndex(max(0, idx))
        self.loading = False
        self.update_enabled()
        self.refresh_preview()
        self.refresh_status()

    def set_field(self, key, val):
        if self.loading or not self.cur:
            return
        self.cur[key] = val
        if key == "name":
            item = self.vlist.currentItem()
            if item:
                item.setText(val)
        if key == "autostart":
            update_autostart(self.win.settings)
        if key == "wrap" and val and self.cur["style"] != "frame":
            self.cur["style"] = "frame"
            self.select(self.vlist.currentRow())
        self.update_enabled()
        self.refresh_preview()
        self.win.schedule_save()

    def add(self, kind):
        v = vis_template(kind)
        if kind == "frame":
            panels = self.win.settings.get("panels", [])
            target = next((x for x in panels if x["kind"] == "nowplaying"), panels[0] if panels else None)
            if target:
                v["wrap"] = target["id"]
                v["name"] = f"Frame around {target['name']}"
        self.items.append(v)
        self.refresh()
        self.vlist.setCurrentRow(len(self.items) - 1)
        self.win.schedule_save()

    def duplicate(self):
        if not self.cur:
            return
        v = copy.deepcopy(self.cur)
        v["id"] = uuid.uuid4().hex[:8]
        v["name"] += " copy"
        self.items.append(v)
        self.refresh()
        self.vlist.setCurrentRow(len(self.items) - 1)
        self.win.schedule_save()

    def delete(self):
        if not self.cur:
            return
        if QMessageBox.question(self, "Delete visualizer", f"Delete “{self.cur['name']}”?") != QMessageBox.Yes:
            return
        stop_visualizer(self.cur["id"])
        self.items.remove(self.cur)
        self.cur = None
        update_autostart(self.win.settings)
        self.refresh()
        self.win.schedule_save()

    def run(self):
        if not self.cur:
            return
        if not shutil.which("cava"):
            QMessageBox.information(self, "cava needed", "Visualizers get their audio data from cava.\n\n"
                                    "Install it with:\n    sudo dnf install cava")
            return
        self.win.save_now()          # the visualizer process reads settings from disk
        if not vis_pids(self.cur["id"]):
            start_visualizer(self.cur)
        QTimer.singleShot(1500, self.refresh_status)

    def stop(self):
        if self.cur:
            stop_visualizer(self.cur["id"])
            QTimer.singleShot(600, self.refresh_status)

    def stop_all(self):
        for v in self.items:
            stop_visualizer(v["id"])
        QTimer.singleShot(600, self.refresh_status)

    def refresh_status(self):
        if not self.isVisible():
            return
        running = set()
        for v in self.items:
            if vis_pids(v["id"]):
                running.add(v["id"])
        for i, v in enumerate(self.items):
            item = self.vlist.item(i)
            if item:
                item.setText(("●  " if v["id"] in running else "") + v["name"])
        on = bool(self.cur and self.cur["id"] in running)
        self.status.setText("● running" if on else "○ not running")
        self.status.setStyleSheet(f"color: {self.win.pal['ansi'][2] if on else self.win.pal['muted']};")


# ── Panels tab ─────────────────────────────────────────────────────

def desktop_dir():
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return HOME / "Desktop"


def copy_shortcuts(files, folder):
    dest = Path(os.path.expanduser(folder))
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in files:
        f = Path(f)
        target = dest / f.name
        if f.is_file() and not target.exists():
            shutil.copy2(f, target)
            n += 1
    return n


class PanelPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.panel = None
        self.pal = None
        self.wall = None
        self.wall_path = None
        self.items = []
        self.icons = {}
        self.folder = None
        self.t = 0.0
        self.setMinimumSize(380, 300)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)

    def set_data(self, panel, p, wallpaper):
        self.panel, self.pal = panel, p
        if wallpaper != self.wall_path:
            self.wall_path = wallpaper
            self.wall = QPixmap(wallpaper) if wallpaper and Path(wallpaper).exists() else None
        if panel and panel["kind"] == "launcher" and panel["folder"] != self.folder:
            self.reload_items()
        self.update()

    def reload_items(self):
        self.folder = self.panel["folder"]
        self.items = launcher_items(self.folder)
        self.icons = {it["path"]: icon_for_item(it) for it in self.items}
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def tick(self):
        self.t += 0.04
        if self.panel and (self.panel["glow"] or self.panel["kind"] == "nowplaying"):
            self.update()

    def paintEvent(self, e):
        p = self.pal
        if not p:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        if self.wall and not self.wall.isNull():
            sc = self.wall.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            qp.drawPixmap(0, 0, sc, (sc.width() - r.width()) // 2, (sc.height() - r.height()) // 2,
                          r.width(), r.height())
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            g.setColorAt(0, QColor(mix(p["background"], "#000000", 0.3)))
            g.setColorAt(1, QColor(mix(p["surface"], p["accent"], 0.3)))
            qp.fillRect(r, g)
        if not self.panel:
            qp.setPen(QColor(p["foreground"]))
            qp.drawText(r, Qt.AlignCenter, "Create or pick a panel")
            return
        panel = self.panel
        items = self.items if panel["kind"] == "launcher" else []
        _lay, full = panel_layout(panel, len(items))
        m = GLOW_MARGIN
        scale = min(1.0, (r.width() - 2 * m) / full.width(), (r.height() - 2 * m) / full.height())
        area = QRectF(m, m, (r.width() - 2 * m) / scale, (r.height() - 2 * m) / scale)
        pos = align_rect(panel["alignment"], 0, 0, full.width(), full.height(), area).topLeft()
        length = 214.0
        np = {"status": "Playing", "title": "Song title", "artist": "Artist name", "art": "",
              "length": length, "position": (self.t * 4) % length}
        glow = bass_level(fake_spectrum(24, self.t)) if panel["glow"] else 0.0
        qp.scale(scale, scale)
        paint_panel(qp, pos, panel, p, {"items": items, "icons": self.icons, "np": np, "glow": glow})
        qp.end()


class PanelsTab(QWidget):
    CONTENT = {
        "launcher": [("folder", "folder", "Shortcuts folder", None), ("columns", "int", "Columns", (1, 12, "")),
                     ("icon_size", "int", "Icon size", (16, 160, " px")), ("labels", "bool", "Show names", None)],
        "nowplaying": [("art_size", "int", "Album art size", (48, 320, " px")),
                       ("progress", "bool", "Progress bar (click to seek)", None),
                       ("controls", "bool", "Playback buttons", None)],
    }
    LOOK = [("name", "text", "Name", None), ("title", "text", "Title", None),
            ("width", "int", "Width", (120, 2000, " px")), ("opacity", "int", "Background", (0, 100, " %")),
            ("radius", "int", "Corner radius", (0, 60, " px")), ("padding", "int", "Padding", (4, 80, " px")),
            ("border", "bool", "Outline", None), ("glow", "bool", "Glow with the bass (needs cava)", None)]
    PLACE = [("alignment", "combo", "Position", ALIGNMENTS), ("gap_x", "int", "Offset  ↔", (-8000, 8000, " px")),
             ("gap_y", "int", "Offset  ↕", (-8000, 8000, " px")), ("screen", "screen", "Screen", None),
             ("x11", "bool", "Pin to exact position (runs through XWayland)", None),
             ("autostart", "bool", "Start when I log in", None)]

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cur = None
        self.loading = False
        self.inputs = {}
        self.content_rows = {}
        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(section_label("Your panels"))
        self.plist = QListWidget()
        self.plist.currentRowChanged.connect(self.select)
        lv.addWidget(self.plist, 1)
        row = QHBoxLayout()
        b_new = QToolButton()
        b_new.setText("New ▾")
        b_new.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b_new)
        for key, label in PANEL_KINDS:
            m.addAction(label.replace("&", "&&")).triggered.connect(lambda *_, k=key: self.add(k))
        b_new.setMenu(m)
        b_dup = QPushButton("Duplicate")
        b_dup.clicked.connect(self.duplicate)
        b_del = QPushButton("Delete")
        b_del.clicked.connect(self.delete)
        for b in (b_new, b_dup, b_del):
            row.addWidget(b)
        lv.addLayout(row)
        lv.addWidget(hint_label("Panels are clickable windows on your desktop, drawn by ThemeForge in your "
                                "palette. The games launcher shows every shortcut in a folder; the now playing "
                                "card shows album art with playback buttons."))
        split.addWidget(left)

        mid_scroll = QScrollArea()
        mid_scroll.setWidgetResizable(True)
        mid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(4, 0, 12, 0)
        mv.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        gb = QGroupBox("Content")
        self.content_form = QFormLayout(gb)
        for kind, fields in self.CONTENT.items():
            for key, ftype, label, opts in fields:
                w = self.make_input(key, ftype, opts)
                if ftype == "bool":
                    w.setText(label)
                    self.content_form.addRow("", w)
                else:
                    self.content_form.addRow(label, w)
                self.inputs[key] = w
                self.content_rows[key] = kind
        self.launcher_tools = QWidget()
        tl = QVBoxLayout(self.launcher_tools)
        tl.setContentsMargins(0, 4, 0, 0)
        for label, fn in (("Copy game shortcuts from my Desktop", self.copy_from_desktop),
                          ("Add apps or games from the app menu…", self.add_apps),
                          ("Open the shortcuts folder", self.open_folder)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            tl.addWidget(b)
        self.content_form.addRow("", self.launcher_tools)
        mv.addWidget(gb)
        for title, fields in (("Look", self.LOOK), ("Placement", self.PLACE)):
            gb = QGroupBox(title)
            f = QFormLayout(gb)
            for key, ftype, label, opts in fields:
                w = self.make_input(key, ftype, opts)
                if ftype == "bool":
                    w.setText(label)
                    f.addRow("", w)
                else:
                    f.addRow(label, w)
                self.inputs[key] = w
            mv.addWidget(gb)
        mv.addStretch()
        mid_scroll.setWidget(mid)
        split.addWidget(mid_scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        self.preview = PanelPreview()
        rv.addWidget(self.preview, 1)
        rv.addWidget(hint_label("Right-click a running panel for more options. While it runs, changes here show "
                                "up on the desktop within a second."))
        row = QHBoxLayout()
        b_run = QPushButton("Run on desktop")
        b_run.setObjectName("primary")
        b_run.clicked.connect(self.run)
        b_stop = QPushButton("Stop")
        b_stop.clicked.connect(self.stop)
        b_all = QPushButton("Stop all")
        b_all.clicked.connect(self.stop_all)
        for b in (b_run, b_stop, b_all):
            row.addWidget(b)
        row.addStretch()
        self.status = QLabel()
        row.addWidget(self.status)
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([260, 420, 580])

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(3000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

    @property
    def items(self):
        return self.win.settings.setdefault("panels", [])

    def make_input(self, key, kind, opts):
        if kind == "text":
            w = QLineEdit()
            w.textEdited.connect(lambda val: self.set_field(key, val))
        elif kind == "int":
            w = spin(opts[0], opts[1], opts[2])
            w.valueChanged.connect(lambda val: self.set_field(key, val))
        elif kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda val: self.set_field(key, val))
        elif kind == "folder":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            w.edit = QLineEdit()
            w.edit.editingFinished.connect(lambda: self.set_field(key, w.edit.text().strip() or "~/Games"))
            b = QPushButton("Browse…")
            b.clicked.connect(self.browse_folder)
            h.addWidget(w.edit, 1)
            h.addWidget(b)
        else:
            w = QComboBox()
            if kind == "screen":
                w.addItem("Primary screen", "")
                for sc in QGuiApplication.screens():
                    w.addItem(f"{sc.name()}  ({sc.geometry().width()}×{sc.geometry().height()})", sc.name())
            else:
                for data, label in opts:
                    w.addItem(label, data)
            w.currentIndexChanged.connect(lambda i, box=w: self.set_field(key, box.itemData(i)))
        return w

    def refresh(self):
        row = self.plist.currentRow()
        self.plist.blockSignals(True)
        self.plist.clear()
        for x in self.items:
            self.plist.addItem(x["name"])
        self.plist.blockSignals(False)
        if self.items:
            self.plist.setCurrentRow(min(max(row, 0), len(self.items) - 1))
        self.select(self.plist.currentRow())

    def refresh_preview(self):
        self.preview.set_data(self.cur, self.win.pal, self.win.settings.get("wallpaper"))

    def select(self, row):
        self.cur = self.items[row] if 0 <= row < len(self.items) else None
        self.loading = True
        kind = self.cur["kind"] if self.cur else None
        for key, w in self.inputs.items():
            w.setEnabled(self.cur is not None)
            if key in self.content_rows:
                self.content_form.setRowVisible(w, self.content_rows[key] == kind)
            if not self.cur:
                continue
            val = self.cur[key]
            if isinstance(w, QLineEdit):
                w.setText(val)
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QComboBox):
                idx = w.findData(val)
                if idx < 0 and key == "screen":
                    w.addItem(f"{val} (not connected)", val)
                    idx = w.count() - 1
                w.setCurrentIndex(max(0, idx))
            else:
                w.edit.setText(val)
        self.content_form.setRowVisible(self.launcher_tools, kind == "launcher")
        self.loading = False
        self.refresh_preview()
        self.refresh_status()

    def set_field(self, key, val):
        if self.loading or not self.cur:
            return
        self.cur[key] = val
        if key == "name":
            item = self.plist.currentItem()
            if item:
                item.setText(val)
        if key == "autostart":
            update_autostart(self.win.settings)
        if key == "folder":
            self.preview.folder = None
        self.refresh_preview()
        self.win.schedule_save()

    def browse_folder(self):
        if not self.cur:
            return
        start = os.path.expanduser(self.cur["folder"])
        path = QFileDialog.getExistingDirectory(self, "Folder with game shortcuts",
                                                start if Path(start).is_dir() else str(HOME))
        if path:
            path = "~" + path[len(str(HOME)):] if path.startswith(str(HOME)) else path
            self.inputs["folder"].edit.setText(path)
            self.set_field("folder", path)

    def copy_from_desktop(self):
        if not self.cur:
            return
        files = sorted(desktop_dir().glob("*.desktop"))
        n = copy_shortcuts(files, self.cur["folder"])
        self.preview.reload_items()
        QMessageBox.information(self, "Shortcuts copied",
                                f"Copied {n} shortcut(s) into {self.cur['folder']}.\n\n"
                                "The originals are still on your Desktop - delete them there if you want a "
                                "clean desktop." if n else
                                f"No new .desktop shortcuts found on {desktop_dir()}.")

    def add_apps(self):
        if not self.cur:
            return
        start = HOME / ".local" / "share" / "applications"
        files, _ = QFileDialog.getOpenFileNames(self, "Pick apps or games (Steam games live here)",
                                                str(start if start.exists() else "/usr/share/applications"),
                                                "App shortcuts (*.desktop)")
        if files:
            copy_shortcuts(files, self.cur["folder"])
            self.preview.reload_items()

    def open_folder(self):
        if self.cur:
            d = Path(os.path.expanduser(self.cur["folder"]))
            d.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def add(self, kind):
        self.items.append(panel_template(kind))
        self.refresh()
        self.plist.setCurrentRow(len(self.items) - 1)
        self.win.schedule_save()

    def duplicate(self):
        if not self.cur:
            return
        x = copy.deepcopy(self.cur)
        x["id"] = uuid.uuid4().hex[:8]
        x["name"] += " copy"
        self.items.append(x)
        self.refresh()
        self.plist.setCurrentRow(len(self.items) - 1)
        self.win.schedule_save()

    def delete(self):
        if not self.cur:
            return
        if QMessageBox.question(self, "Delete panel", f"Delete “{self.cur['name']}”?") != QMessageBox.Yes:
            return
        stop_panel(self.cur["id"])
        for v in self.win.settings.get("visualizers", []):
            if v.get("wrap") == self.cur["id"]:
                v["wrap"] = ""
        self.items.remove(self.cur)
        self.cur = None
        update_autostart(self.win.settings)
        self.refresh()
        self.win.schedule_save()

    def run(self):
        if not self.cur:
            return
        if self.cur["kind"] == "nowplaying" and not shutil.which("playerctl"):
            QMessageBox.information(self, "playerctl needed", "The now playing card reads your music player "
                                    "through playerctl.\n\nInstall it with:\n    sudo dnf install playerctl")
        if self.cur["kind"] == "launcher":
            Path(os.path.expanduser(self.cur["folder"])).mkdir(parents=True, exist_ok=True)
        self.win.save_now()
        if not panel_pids(self.cur["id"]):
            start_panel(self.cur)
        QTimer.singleShot(1500, self.refresh_status)

    def stop(self):
        if self.cur:
            stop_panel(self.cur["id"])
            QTimer.singleShot(600, self.refresh_status)

    def stop_all(self):
        for x in self.items:
            stop_panel(x["id"])
        QTimer.singleShot(600, self.refresh_status)

    def refresh_status(self):
        if not self.isVisible():
            return
        running = {x["id"] for x in self.items if panel_pids(x["id"])}
        for i, x in enumerate(self.items):
            item = self.plist.item(i)
            if item:
                item.setText(("●  " if x["id"] in running else "") + x["name"])
        on = bool(self.cur and self.cur["id"] in running)
        self.status.setText("● running" if on else "○ not running")
        self.status.setStyleSheet(f"color: {self.win.pal['ansi'][2] if on else self.win.pal['muted']};")


# ── Profiles tab ───────────────────────────────────────────────────

class SwatchStrip(QWidget):
    def __init__(self):
        super().__init__()
        self.cols = []
        self.setFixedHeight(22)

    def set_colors(self, cols):
        self.cols = list(cols)
        self.update()

    def paintEvent(self, e):
        if not self.cols:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w = self.width() / len(self.cols)
        for i, c in enumerate(self.cols):
            qp.fillRect(QRectF(i * w, 0, w + 0.5, self.height()), QColor(c))
        qp.end()


def palette_strip(p):
    return [p["background"], p["surface"], p["accent"], p["accent2"]] + p["ansi"][1:7] + [p["foreground"]]


class ProfilesTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.loading = False
        outer = QHBoxLayout(self)
        split = QSplitter()
        outer.addWidget(split)

        # profiles
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 10, 0)
        gb = QGroupBox("Desktop profiles")
        v = QVBoxLayout(gb)
        v.addWidget(hint_label("A profile remembers your colors, wallpaper, what Apply changes, album-art mode, "
                               "and which widgets, visualizers and panels are running - so “Gaming” and “Chill” "
                               "are one click apart."))
        self.plist = QListWidget()
        self.plist.setIconSize(self.plist.iconSize() * 1.4)
        self.plist.currentRowChanged.connect(self.show_details)
        self.plist.itemDoubleClicked.connect(lambda *_: self.switch())
        v.addWidget(self.plist, 1)
        self.details = hint_label("")
        v.addWidget(self.details)
        self.strip = SwatchStrip()
        v.addWidget(self.strip)
        row = QHBoxLayout()
        b_switch = QPushButton("Switch to it")
        b_switch.setObjectName("primary")
        b_switch.clicked.connect(self.switch)
        b_save = QPushButton("Save current setup as…")
        b_save.clicked.connect(self.save_new)
        row.addWidget(b_switch)
        row.addWidget(b_save)
        v.addLayout(row)
        row = QHBoxLayout()
        for label, fn in (("Update with current setup", self.update_selected), ("Rename…", self.rename),
                          ("Delete", self.delete)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        lv.addWidget(gb, 1)

        gb = QGroupBox("Tray icon && keyboard shortcut")
        v = QVBoxLayout(gb)
        self.tray_cb = QCheckBox("Show ThemeForge in the system tray (switch profiles and themes from there)")
        self.tray_cb.toggled.connect(self.toggle_tray)
        v.addWidget(self.tray_cb)
        b_short = QPushButton("Set up a keyboard shortcut for “Next profile”…")
        b_short.clicked.connect(self.setup_shortcut)
        v.addWidget(b_short)
        v.addWidget(hint_label("Middle-click the tray icon for the next profile. From a terminal or script: "
                               "themeforge --profile Gaming, themeforge --next-profile"))
        lv.addWidget(gb)
        split.addWidget(left)

        # album-art mode
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 0, 0, 0)
        gb = QGroupBox("Album-art mode")
        v = QVBoxLayout(gb)
        self.album_cb = QCheckBox("Recolor my desktop to match the album art of whatever is playing")
        self.album_cb.setStyleSheet("font-weight: bold;")
        self.album_cb.toggled.connect(lambda on: self.set_album("enabled", on))
        v.addWidget(self.album_cb)
        v.addWidget(hint_label("Works with any player that shows up in playerctl - Spotify, browsers, mpv, "
                               "Strawberry, Elisa… Your saved theme isn't touched; ThemeForge goes back to it when "
                               "you turn this off."))
        v.addWidget(section_label("What follows the album art"))
        grid = QGridLayout()
        self.album_targets = {}
        for i, (key, label) in enumerate(ALBUM_TARGETS):
            cb = QCheckBox(label.replace("&", "&&"))
            cb.toggled.connect(lambda on, k=key: self.toggle_album_target(k, on))
            self.album_targets[key] = cb
            grid.addWidget(cb, i // 2, i % 2)
        v.addLayout(grid)
        self.album_light = QCheckBox("Use light palettes")
        self.album_light.toggled.connect(lambda on: self.set_album("light", on))
        self.album_revert = QCheckBox("Go back to my own theme when the music stops (after 15 seconds)")
        self.album_revert.toggled.connect(lambda on: self.set_album("revert", on))
        v.addWidget(self.album_light)
        v.addWidget(self.album_revert)
        v.addWidget(section_label("Right now"))
        self.album_status = QLabel("Off")
        self.album_status.setWordWrap(True)
        v.addWidget(self.album_status)
        self.album_strip = SwatchStrip()
        v.addWidget(self.album_strip)
        v.addStretch()
        rv.addWidget(gb, 1)
        split.addWidget(right)
        split.setSizes([620, 620])

        self.timer = QTimer(self)
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self.refresh_album_status)
        self.timer.start()

    @property
    def s(self):
        return self.win.settings

    def refresh(self):
        self.loading = True
        row = self.plist.currentRow()
        self.plist.clear()
        for x in self.s["profiles"]:
            cur = x["name"] == self.s.get("current_profile")
            self.plist.addItem(x["name"] + ("   ★ active" if cur else ""))
            self.plist.item(self.plist.count() - 1).setIcon(palette_icon(x["palette"], 48))
        if self.s["profiles"]:
            self.plist.setCurrentRow(min(max(row, 0), len(self.s["profiles"]) - 1))
        self.show_details(self.plist.currentRow())
        al = self.s["album"]
        self.album_cb.setChecked(bool(al.get("enabled")))
        for key, cb in self.album_targets.items():
            cb.setChecked(key in al.get("targets", []))
        self.album_light.setChecked(bool(al.get("light")))
        self.album_revert.setChecked(bool(al.get("revert", True)))
        self.tray_cb.setChecked(bool(self.s.get("tray")))
        self.loading = False
        self.refresh_album_status()

    def selected(self):
        i = self.plist.currentRow()
        return self.s["profiles"][i] if 0 <= i < len(self.s["profiles"]) else None

    def show_details(self, _row):
        x = self.selected()
        if not x:
            self.details.setText("No profiles yet. Set your desktop up the way you like it, then "
                                 "“Save current setup as…”.")
            self.strip.set_colors([])
            return
        bits = [f"Palette: {x['palette'].get('name', 'custom')}"]
        for key, word in (("widgets", "widget"), ("visualizers", "visualizer"), ("panels", "panel")):
            n = len(x.get(key, []))
            bits.append(f"{n} {word}{'s' if n != 1 else ''}")
        if x.get("album"):
            bits.append("album-art mode on")
        if x.get("wallpaper"):
            bits.append(f"wallpaper {Path(x['wallpaper']).name}")
        self.details.setText(" · ".join(bits))
        self.strip.set_colors(palette_strip(x["palette"]))

    def save_new(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name (e.g. Gaming, Chill, Work):")
        name = (name or "").strip()
        if not ok or not name:
            return
        if any(x["name"] == name for x in self.s["profiles"]) and QMessageBox.question(
                self, "Save profile", f"Replace “{name}”?") != QMessageBox.Yes:
            return
        save_profile(self.s, name)
        self.win.save_now()
        self.refresh()
        self.win.statusBar().showMessage(f"Saved profile “{name}”", 5000)

    def update_selected(self):
        x = self.selected()
        if x:
            save_profile(self.s, x["name"])
            self.win.save_now()
            self.refresh()

    def rename(self):
        x = self.selected()
        if not x:
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=x["name"])
        name = (name or "").strip()
        if ok and name and name != x["name"]:
            if self.s.get("current_profile") == x["name"]:
                self.s["current_profile"] = name
            x["name"] = name
            self.win.save_now()
            self.refresh()

    def delete(self):
        x = self.selected()
        if x and QMessageBox.question(self, "Delete profile", f"Delete “{x['name']}”?") == QMessageBox.Yes:
            self.s["profiles"].remove(x)
            if self.s.get("current_profile") == x["name"]:
                self.s["current_profile"] = ""
            self.win.save_now()
            self.refresh()

    def switch(self):
        x = self.selected()
        if not x:
            return
        log = self.win.targets_tab.append_log
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            switch_profile(self.s, x["name"], log)
        except Exception as e:
            QMessageBox.warning(self, "Switch profile", str(e))
        finally:
            QApplication.restoreOverrideCursor()
        self.win.note_saved()
        self.win.reload_everything(from_disk=False)
        self.win.statusBar().showMessage(f"Switched to “{x['name']}”", 6000)

    def set_album(self, key, val):
        if self.loading:
            return
        self.s["album"][key] = val
        self.service_settings_changed()

    def toggle_album_target(self, key, on):
        if self.loading:
            return
        t = [k for k in self.s["album"].get("targets", []) if k != key]
        if on:
            t.append(key)
        self.s["album"]["targets"] = t
        self.service_settings_changed()

    def toggle_tray(self, on):
        if self.loading:
            return
        self.s["tray"] = on
        self.service_settings_changed()

    def service_settings_changed(self):
        self.win.save_now()
        update_autostart(self.s)
        if service_wanted(self.s):
            if self.s["album"].get("enabled") and not shutil.which("playerctl"):
                QMessageBox.information(self, "playerctl needed", "Album-art mode reads your music player "
                                        "through playerctl.\n\nInstall it with:\n    sudo dnf install playerctl")
            ensure_service()

    def setup_shortcut(self):
        path = install_shortcut_entry()
        QMessageBox.information(
            self, "Keyboard shortcut",
            "Added “ThemeForge: Next profile” to your app menu.\n\n"
            "System Settings will open on the Shortcuts page. There:\n"
            "  1. Click “Add New” → “Application…”\n"
            "  2. Pick “ThemeForge: Next profile”\n"
            "  3. Click its shortcut button and press the keys you want (e.g. Meta+Shift+T)\n\n"
            f"({path})")
        subprocess.Popen(["systemsettings", "kcm_keys"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def refresh_album_status(self):
        if not self.isVisible():
            return
        al = self.s["album"]
        if not al.get("enabled"):
            self.album_status.setText("Off")
            self.album_strip.set_colors([])
            return
        running = bool(tf_pids("--service"))
        try:
            st = json.loads(ALBUM_STATUS_FILE.read_text())
        except Exception:
            st = {}
        if not running:
            self.album_status.setText("Starting…")
        elif st.get("state") == "on":
            self.album_status.setText(f"Matching <b>{st.get('title') or 'Unknown'}</b> — {st.get('artist') or ''}")
            self.album_strip.set_colors(palette_strip(st["palette"]) if valid_palette(st.get("palette", {}))
                                        else [])
        else:
            self.album_status.setText("Waiting for music…")
            self.album_strip.set_colors([])


# ── Targets tab ────────────────────────────────────────────────────

class TargetsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        outer = QHBoxLayout(self)
        split = QSplitter()
        outer.addWidget(split)

        # left: the targets, scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(420)
        inner = QWidget()
        lv = QVBoxLayout(inner)
        lv.setContentsMargins(0, 0, 10, 0)
        lv.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        gb = QGroupBox("What “Apply to desktop” changes")
        g = QGridLayout(gb)
        g.setColumnStretch(0, 1)
        g.setVerticalSpacing(2)
        self.checks = {}
        for i, (key, name, desc, exe, _fn) in enumerate(TARGETS):
            cb = QCheckBox(name.replace("&", "&&"))
            cb.setStyleSheet("font-weight: bold;")
            cb.toggled.connect(lambda on, k=key: self.toggle(k, on))
            self.checks[key] = cb
            ok, why = target_available(exe)
            st = QLabel("" if ok else "not installed")
            st.setObjectName("warn")
            st.setToolTip(why)
            cb.setToolTip(desc)
            g.addWidget(cb, i * 2, 0)
            g.addWidget(st, i * 2, 1, Qt.AlignRight)
            d = hint_label(desc)
            d.setContentsMargins(26, 0, 0, 8)
            g.addWidget(d, i * 2 + 1, 0, 1, 2)
        lv.addWidget(gb)
        lv.addStretch()
        scroll.setWidget(inner)
        split.addWidget(scroll)

        # right: options, actions, log, updates
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(10, 0, 0, 0)
        gb = QGroupBox("Options")
        f = QFormLayout(gb)
        self.icon_box = QComboBox()
        self.icon_box.addItem("Keep my current icon theme", "")
        for name in sorted(installed_icon_themes(), key=str.lower):
            self.icon_box.addItem(name, name)
        self.icon_box.currentIndexChanged.connect(
            lambda i: self.set_opt("icon_theme", self.icon_box.itemData(i)))
        f.addRow("Icon theme", self.icon_box)
        self.papirus = QCheckBox("Recolor Papirus folders to match the accent")
        self.papirus.toggled.connect(lambda on: self.set_opt("papirus_folders", on))
        f.addRow("", self.papirus)
        self.kde_accent = QCheckBox("Set the KDE accent color too")
        self.kde_accent.toggled.connect(lambda on: self.set_opt("kde_accent", on))
        f.addRow("", self.kde_accent)
        clients = discord_clients()
        f.addRow("Discord", QLabel(", ".join(n for n, _ in clients) if clients else "no theme-capable client found"))
        b_exports = QPushButton("Open exported themes folder")
        b_exports.clicked.connect(lambda *_: (EXPORT_DIR.mkdir(parents=True, exist_ok=True),
                                              QDesktopServices.openUrl(QUrl.fromLocalFile(str(EXPORT_DIR)))))
        f.addRow("Vivaldi", b_exports)
        v.addWidget(gb)

        row = QHBoxLayout()
        b_apply = QPushButton("Apply to desktop")
        b_apply.setObjectName("primary")
        b_apply.clicked.connect(self.win.apply_desktop)
        b_restore = QPushButton("Restore my original files…")
        b_restore.clicked.connect(self.restore)
        b_folder = QPushButton("Open ThemeForge folder")
        b_folder.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl.fromLocalFile(str(CFG_DIR))))
        row.addWidget(b_apply)
        row.addWidget(b_restore)
        row.addWidget(b_folder)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(section_label("Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        v.addWidget(self.log, 1)
        v.addWidget(hint_label(
            "Before changing any of your config files for the first time, ThemeForge copies the original "
            f"into {ORIG_DIR}. “Restore” puts those back, plus your KDE colors, accent and icon theme."))
        split.addWidget(right)
        split.setSizes([560, 720])

        gb = QGroupBox("Updates")
        row = QHBoxLayout(gb)
        row.addWidget(QLabel(f"ThemeForge {VERSION}"))
        self.auto_update = QCheckBox("Check for updates when ThemeForge starts")
        self.auto_update.toggled.connect(self.toggle_auto_update)
        row.addWidget(self.auto_update)
        b_check = QPushButton("Check now")
        b_check.clicked.connect(lambda *_: self.win.check_updates(manual=True))
        row.addWidget(b_check)
        self.update_status = QLabel()
        self.update_status.setObjectName("muted")
        row.addWidget(self.update_status, 1)
        b_gh = QPushButton("GitHub page")
        b_gh.clicked.connect(lambda *_: QDesktopServices.openUrl(QUrl(f"https://github.com/{GITHUB_REPO}")))
        row.addWidget(b_gh)
        v.addWidget(gb)
        if is_git_checkout():
            self.update_status.setText("Running from a git checkout - update with git pull.")

    def toggle_auto_update(self, on):
        self.win.settings["check_updates"] = on
        self.win.schedule_save()

    def set_opt(self, key, val):
        self.win.settings[key] = val
        self.win.schedule_save()

    def refresh(self):
        st = self.win.settings
        for key, cb in self.checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(st["targets"].get(key)))
            cb.blockSignals(False)
        for w, val in ((self.papirus, st.get("papirus_folders", True)), (self.kde_accent, st.get("kde_accent", True))):
            w.blockSignals(True)
            w.setChecked(bool(val))
            w.blockSignals(False)
        self.icon_box.blockSignals(True)
        idx = self.icon_box.findData(st.get("icon_theme", ""))
        if idx < 0:
            self.icon_box.addItem(f"{st['icon_theme']} (not installed)", st["icon_theme"])
            idx = self.icon_box.count() - 1
        self.icon_box.setCurrentIndex(idx)
        self.icon_box.blockSignals(False)
        self.auto_update.blockSignals(True)
        self.auto_update.setChecked(bool(self.win.settings.get("check_updates", True)))
        self.auto_update.blockSignals(False)

    def toggle(self, key, on):
        self.win.settings["targets"][key] = on
        if key == "wallpaper":
            self.win.colors_tab.refresh()
        self.win.schedule_save()

    def append_log(self, text):
        self.log.appendPlainText(text)
        QApplication.processEvents()

    def restore(self):
        if QMessageBox.question(self, "Restore originals",
                                "Put back the files ThemeForge changed, as they were before its first apply?"
                                ) != QMessageBox.Yes:
            return
        self.log.appendPlainText(f"— Restoring originals at {time.strftime('%H:%M:%S')} —")
        restore_originals(self.win.settings, self.append_log)
        self.win.save_now()


class CommunityDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.themes = []
        self.setWindowTitle("Community themes")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        v.addWidget(hint_label(f"Themes shared by other ThemeForge users in github.com/{GITHUB_REPO}. "
                               "Installing one adds it to your Theme list - nothing changes until you Apply."))
        self.status = QLabel("Loading…")
        self.status.setObjectName("muted")
        v.addWidget(self.status)
        self.list = QListWidget()
        self.list.setIconSize(QSize(180, 28))
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemDoubleClicked.connect(lambda *_: self.install(True))
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_share = QPushButton("How to share yours")
        b_share.clicked.connect(lambda *_: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{GITHUB_REPO}/blob/main/CONTRIBUTING.md")))
        row.addWidget(b_share)
        row.addStretch()
        b_install = QPushButton("Install")
        b_install.clicked.connect(lambda *_: self.install(False))
        b_use = QPushButton("Install && use")
        b_use.setObjectName("primary")
        b_use.clicked.connect(lambda *_: self.install(True))
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        for b in (b_install, b_use, b_close):
            row.addWidget(b)
        v.addLayout(row)
        win.run_in_thread(fetch_community_themes, self.loaded)

    def loaded(self, themes, err):
        if err:
            self.status.setText(f"Couldn't load community themes: {err}")
            return
        self.themes = themes or []
        mine = set(list_user_themes())
        self.status.setText(f"{len(self.themes)} themes")
        for t in self.themes:
            pm = QPixmap(180, 28)
            pm.fill(Qt.transparent)
            qp = QPainter(pm)
            cols = palette_strip(t["palette"])
            w = 180 / len(cols)
            for i, c in enumerate(cols):
                qp.fillRect(QRectF(i * w, 0, w + 0.5, 28), QColor(c))
            qp.end()
            label = t["name"] + (f"  ·  by {t['author']}" if t["author"] else "")
            if t["name"] in mine:
                label += "  ·  installed"
            if t["description"]:
                label += f"\n{t['description']}"
            item = QListWidgetItem(QIcon(pm), label)
            self.list.addItem(item)
        if self.themes:
            self.list.setCurrentRow(0)

    def install(self, use):
        i = self.list.currentRow()
        if not 0 <= i < len(self.themes):
            return
        t = self.themes[i]
        if t["name"] in list_user_themes():
            name = t["name"]
        else:
            name = self.win.install_theme(t["palette"], t["name"])
        self.win.populate_presets(self.win.pal.get("name"))
        if use:
            self.win.set_palette(load_user_theme(name))
            self.accept()
        else:
            self.list.item(i).setText(self.list.item(i).text().split("\n")[0] + "  ·  installed")


class _Bridge(QObject):
    """Carries a background thread's result back to the GUI thread."""
    done = Signal(object, object)


# ── main window ────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("ThemeForge")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-color"))
        self.resize(1320, 860)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(16, 12, 16, 8)
        top = QHBoxLayout()
        title = QLabel("ThemeForge")
        title.setObjectName("title")
        sub = QLabel("one palette for your whole desktop")
        sub.setObjectName("muted")
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(sub)
        top.addStretch()
        top.addWidget(QLabel("Theme"))
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(220)
        self.preset_box.setPlaceholderText("Custom")
        self.preset_box.activated.connect(self.load_preset)
        top.addWidget(self.preset_box)
        b_save = QPushButton("Save as…")
        b_save.clicked.connect(self.save_theme)
        self.b_del = QPushButton("Delete")
        self.b_del.clicked.connect(self.delete_theme)
        b_more = QToolButton()
        b_more.setText("More ▾")
        b_more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(b_more)
        mm.addAction("Browse community themes…").triggered.connect(self.browse_community)
        mm.addAction("Import a theme file…").triggered.connect(self.import_theme)
        mm.addAction("Export this theme…").triggered.connect(self.export_theme)
        mm.addSeparator()
        mm.addAction("Share your theme on GitHub").triggered.connect(lambda *_: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{GITHUB_REPO}/blob/main/CONTRIBUTING.md")))
        b_more.setMenu(mm)
        top.addWidget(b_save)
        top.addWidget(self.b_del)
        top.addWidget(b_more)
        top.addSpacing(10)
        b_apply = QPushButton("Apply to desktop")
        b_apply.setObjectName("primary")
        b_apply.clicked.connect(self.apply_desktop)
        top.addWidget(b_apply)
        v.addLayout(top)

        # "new version available" banner, hidden until the updater finds something
        self.pending_release = None
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 6, 8, 6)
        self.banner_text = QLabel()
        bl.addWidget(self.banner_text, 1)
        for label, fn, primary in (("What's new", self.open_release, False),
                                   ("Update now", self.update_now, True),
                                   ("Skip this version", self.skip_version, False),
                                   ("✕", self.banner_close, False)):
            b = QPushButton(label)
            if primary:
                b.setObjectName("primary")
                self.banner_update_btn = b
            b.clicked.connect(fn)
            bl.addWidget(b)
        self.banner.hide()
        v.addWidget(self.banner)
        self._bridges = []

        self.tabs = QTabWidget()
        self.colors_tab = ColorsTab(self)
        self.widgets_tab = WidgetsTab(self)
        self.vis_tab = VisualizersTab(self)
        self.panels_tab = PanelsTab(self)
        self.profiles_tab = ProfilesTab(self)
        self.targets_tab = TargetsTab(self)
        self.tabs.addTab(self.colors_tab, "Colors")
        self.tabs.addTab(self.widgets_tab, "Widgets")
        self.tabs.addTab(self.vis_tab, "Visualizers")
        self.tabs.addTab(self.panels_tab, "Panels")
        self.tabs.addTab(self.profiles_tab, "Profiles")
        self.tabs.addTab(self.targets_tab, "Apply && targets")
        v.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.qss_timer = QTimer(self)
        self.qss_timer.setSingleShot(True)
        self.qss_timer.setInterval(120)
        self.qss_timer.timeout.connect(self.restyle)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(800)
        self.save_timer.timeout.connect(self.save_now)

        self.own_mtime = _mtime(SETTINGS_FILE)
        self.ext_timer = QTimer(self)
        self.ext_timer.setInterval(1500)
        self.ext_timer.timeout.connect(self.check_external_changes)
        self.ext_timer.start()

        self.populate_presets(self.pal.get("name"))
        self.restyle()
        self.refresh_tabs()
        self.statusBar().showMessage(f"ThemeForge {VERSION} - edits are previewed here; "
                                     "nothing on your desktop changes until you Apply.")
        QTimer.singleShot(2500, self.maybe_check_updates)

    @property
    def pal(self):
        return self.settings["palette"]

    # ── palette editing
    def set_palette(self, p):
        self.settings["palette"] = copy.deepcopy(p)
        self.populate_presets(p.get("name"))
        self.colors_tab.refresh()
        self.palette_changed()

    def mark_custom(self):
        if self.pal.get("name") in PRESETS or self.pal.get("name") in list_user_themes():
            self.pal["name"] = self.pal["name"] + " (edited)"
        self.preset_box.setCurrentIndex(-1)

    def edit_palette(self, key, c):
        self.pal[key] = c
        self.mark_custom()
        self.palette_changed()

    def edit_ansi(self, i, c):
        self.pal["ansi"][i] = c
        self.mark_custom()
        self.palette_changed()

    def edit_gradient(self, i, c):
        self.pal["gradient"][i] = c
        self.mark_custom()
        self.palette_changed()

    def set_gradient(self, g):
        self.pal["gradient"] = list(g)
        self.mark_custom()
        self.colors_tab.refresh()
        self.palette_changed()

    def refresh_tabs(self):
        for tab in (self.colors_tab, self.widgets_tab, self.vis_tab, self.panels_tab, self.profiles_tab,
                    self.targets_tab):
            tab.refresh()

    def reload_everything(self, from_disk=True):
        if from_disk:
            self.settings = load_settings()
            self.own_mtime = _mtime(SETTINGS_FILE)
        self.populate_presets(self.pal.get("name"))
        self.restyle()
        self.refresh_tabs()

    def note_saved(self):
        self.own_mtime = _mtime(SETTINGS_FILE)

    def check_external_changes(self):
        """The tray, a shortcut or album-art mode may have changed the settings file."""
        m = _mtime(SETTINGS_FILE)
        if m and m != self.own_mtime and not self.save_timer.isActive():
            self.reload_everything()
            self.statusBar().showMessage("Picked up changes made outside this window.", 4000)

    def palette_changed(self):
        self.colors_tab.preview.set_palette(self.pal)
        self.widgets_tab.refresh_preview()
        self.vis_tab.refresh_preview()
        self.panels_tab.refresh_preview()
        self.widgets_tab.build_block_form()
        self.qss_timer.start()
        self.schedule_save()

    def restyle(self):
        QApplication.instance().setStyleSheet(app_qss(self.pal))

    # ── presets / saved themes
    def populate_presets(self, select=None):
        box = self.preset_box
        box.blockSignals(True)
        box.clear()
        for name in PRESETS:
            box.addItem(name, ("builtin", name))
        users = list_user_themes()
        if users:
            box.insertSeparator(box.count())
            for name in users:
                box.addItem(f"★ {name}", ("user", name))
        idx = -1
        for i in range(box.count()):
            d = box.itemData(i)
            if d and d[1] == select:
                idx = i
        box.setCurrentIndex(idx)
        box.blockSignals(False)
        d = box.currentData()
        self.b_del.setEnabled(bool(d and d[0] == "user"))

    def load_preset(self, idx):
        d = self.preset_box.itemData(idx)
        if not d:
            return
        kind, name = d
        if kind == "builtin":
            p = copy.deepcopy(PRESETS[name])
        else:
            try:
                p = load_user_theme(name)
            except Exception as e:
                QMessageBox.warning(self, "ThemeForge", f"Couldn't load that theme: {e}")
                return
        self.set_palette(p)

    def save_theme(self):
        name, ok = QInputDialog.getText(self, "Save theme", "Theme name:",
                                        text=self.pal.get("name", "").replace(" (edited)", ""))
        name = re.sub(r"[/\\:*?\"<>|]", "", name or "").strip()
        if not ok or not name:
            return
        THEMES_DIR.mkdir(parents=True, exist_ok=True)
        path = THEMES_DIR / f"{name}.json"
        if path.exists() and QMessageBox.question(self, "Save theme", f"Replace “{name}”?") != QMessageBox.Yes:
            return
        self.pal["name"] = name
        path.write_text(json.dumps(self.pal, indent=2))
        self.populate_presets(name)
        self.save_now()
        self.statusBar().showMessage(f"Saved “{name}”", 4000)

    def delete_theme(self):
        d = self.preset_box.currentData()
        if not d or d[0] != "user":
            return
        if QMessageBox.question(self, "Delete theme", f"Delete saved theme “{d[1]}”?") == QMessageBox.Yes:
            (THEMES_DIR / f"{d[1]}.json").unlink(missing_ok=True)
            self.populate_presets(None)

    # ── sharing themes
    def install_theme(self, p, name=None):
        name = re.sub(r"[/\\:*?\"<>|]", "", name or p.get("name") or "Imported").strip() or "Imported"
        THEMES_DIR.mkdir(parents=True, exist_ok=True)
        base, n = name, 2
        while (THEMES_DIR / f"{name}.json").exists():
            name = f"{base} {n}"
            n += 1
        p = copy.deepcopy(p)
        p["name"] = name
        (THEMES_DIR / f"{name}.json").write_text(json.dumps(p, indent=2))
        return name

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a ThemeForge theme", str(HOME), "Themes (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
            p = data.get("palette", data)
            p.setdefault("name", data.get("name") or Path(path).stem)
            if "gradient" not in p and all(k in p for k, _ in ROLES) and len(p.get("ansi", [])) == 16:
                p["gradient"] = default_gradient(p)
            if not valid_palette(p):
                raise ValueError("it isn't a ThemeForge theme (some colors are missing)")
        except Exception as e:
            QMessageBox.warning(self, "Import theme", f"Couldn't import {Path(path).name}:\n{e}")
            return
        name = self.install_theme(p)
        self.set_palette(load_user_theme(name))
        self.statusBar().showMessage(f"Imported “{name}”", 5000)

    def export_theme(self):
        name = self.pal.get("name", "My theme").replace(" (edited)", "")
        fname = re.sub(r"[^\w -]", "", name).strip() or "theme"
        path, _ = QFileDialog.getSaveFileName(self, "Export this theme", str(HOME / f"{fname}.json"),
                                              "Themes (*.json)")
        if path:
            author = self.settings.get("theme_author", "")
            out = {"name": name, "author": author, "description": "", "palette": self.pal}
            Path(path).write_text(json.dumps(out, indent=2))
            self.statusBar().showMessage(f"Exported to {path}", 6000)

    def browse_community(self):
        CommunityDialog(self).exec()

    # ── applying / saving
    def apply_desktop(self):
        self.save_now()
        log = self.targets_tab.append_log
        log(f"— Applying “{self.pal.get('name', 'custom')}” at {time.strftime('%H:%M:%S')} —")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = apply_all(self.settings, log)
        finally:
            QApplication.restoreOverrideCursor()
        log("")
        self.save_now()
        self.widgets_tab.refresh_status()
        self.statusBar().showMessage(f"Applied to {n} target(s) — details on the Apply & targets tab.", 8000)

    # ── updates
    def run_in_thread(self, fn, callback):
        bridge = _Bridge()
        bridge.done.connect(callback)
        self._bridges.append(bridge)

        def work():
            try:
                res, err = fn(), None
            except Exception as e:
                res, err = None, e
            bridge.done.emit(res, err)

        threading.Thread(target=work, daemon=True).start()

    def maybe_check_updates(self):
        s = self.settings
        if not s.get("check_updates", True) or is_git_checkout():
            return
        if time.time() - s.get("last_update_check", 0) < 6 * 3600:
            return
        self.check_updates(manual=False)

    def check_updates(self, manual=False):
        if is_git_checkout():
            if manual:
                QMessageBox.information(self, "Updates", "This copy of ThemeForge is a git checkout.\n"
                                        "Update it with:  git pull")
            return
        self.targets_tab.update_status.setText("Checking GitHub…")
        self.run_in_thread(check_for_update, lambda rel, err: self.on_update_checked(rel, err, manual))

    def on_update_checked(self, rel, err, manual):
        self.settings["last_update_check"] = time.time()
        self.schedule_save()
        status = self.targets_tab.update_status
        if err:
            status.setText(f"Couldn't check: {err}")
            if manual:
                QMessageBox.warning(self, "Updates", f"Couldn't check for updates:\n{err}")
            return
        if not rel:
            status.setText(f"You're on the latest version ({VERSION}).")
            return
        status.setText(f"Version {rel['version']} is available.")
        if not manual and rel["version"] == self.settings.get("skip_version"):
            return
        self.pending_release = rel
        if is_system_install():
            self.banner_text.setText(f"<b>ThemeForge {rel['version']}</b> is out — you have {VERSION}. "
                                     "Update it with <code>sudo dnf upgrade themeforge</code>.")
            self.banner_update_btn.hide()
        else:
            self.banner_text.setText(f"<b>ThemeForge {rel['version']}</b> is out — you have {VERSION}.")
            self.banner_update_btn.setEnabled(True)
        self.banner.show()

    def open_release(self):
        if self.pending_release:
            QDesktopServices.openUrl(QUrl(self.pending_release["url"]))

    def skip_version(self):
        if self.pending_release:
            self.settings["skip_version"] = self.pending_release["version"]
            self.schedule_save()
        self.banner.hide()

    def banner_close(self):
        self.banner.hide()

    def update_now(self):
        rel = self.pending_release
        if not rel:
            return
        self.banner_update_btn.setEnabled(False)
        self.banner_text.setText(f"Downloading ThemeForge {rel['version']}…")
        self.run_in_thread(lambda: install_update(rel), self.on_updated)

    def on_updated(self, version, err):
        if err:
            self.banner_update_btn.setEnabled(True)
            self.banner_text.setText("Update failed.")
            QMessageBox.warning(self, "Update failed", f"ThemeForge wasn't changed:\n{err}")
            return
        self.banner.hide()
        self.targets_tab.update_status.setText(f"Updated to {version} - restart to use it.")
        if QMessageBox.question(self, "Update installed",
                                f"ThemeForge {version} is installed.\nRestart now?") == QMessageBox.Yes:
            self.restart()

    def restart(self):
        self.save_now()
        # running windows and the service are still the old code - restart them too
        for v in self.settings.get("visualizers", []):
            if vis_pids(v["id"]):
                stop_visualizer(v["id"])
                start_visualizer(v)
        for x in self.settings.get("panels", []):
            if panel_pids(x["id"]):
                stop_panel(x["id"])
                start_panel(x)
        if tf_pids("--service"):
            stop_tf_process("--service")
            for _ in range(30):
                if not tf_pids("--service"):
                    break
                time.sleep(0.1)
            ensure_service()
        os.execv(sys.executable, [sys.executable, str(SCRIPT)])

    def schedule_save(self):
        self.save_timer.start()

    def save_now(self):
        self.save_timer.stop()
        try:
            save_settings(self.settings)
            self.own_mtime = _mtime(SETTINGS_FILE)
        except Exception as e:
            self.statusBar().showMessage(f"Couldn't save settings: {e}", 8000)

    def closeEvent(self, e):
        self.save_now()
        super().closeEvent(e)


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(f"ThemeForge {VERSION}")
        return
    for flag, cls in (("--visualizer", VisualizerWindow), ("--panel", PanelWindow)):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                run_desktop_window(cls, args[i + 1], flag)
            return
    if "--service" in args:
        run_service()
        return
    if "--list-profiles" in args:
        s = load_settings()
        for x in s["profiles"]:
            print(("* " if x["name"] == s.get("current_profile") else "  ") + x["name"])
        return
    if "--profile" in args or "--next-profile" in args:
        s = load_settings()
        if "--next-profile" in args:
            name = next_profile_name(s)
        else:
            i = args.index("--profile")
            name = " ".join(args[i + 1:]).strip()
        if not name:
            print("No profiles saved yet - save one on ThemeForge's Profiles tab.", file=sys.stderr)
            notify("ThemeForge", "You haven't saved any profiles yet.")
            sys.exit(1)
        try:
            switch_profile(s, name, print)
            notify(f"Profile: {name}")
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        return
    if "--update" in args:
        try:
            rel = check_for_update()
            if not rel:
                print(f"ThemeForge {VERSION} is the latest version.")
                return
            print(f"Updating {VERSION} → {rel['version']}…")
            print(f"Installed ThemeForge {install_update(rel)}. Restart ThemeForge to use it.")
        except Exception as e:
            print(f"Update failed: {e}", file=sys.stderr)
            sys.exit(1)
        return
    if "--restore" in args:
        s = load_settings()
        restore_originals(s, print)
        save_settings(s)
        return
    if "--apply" in args:
        s = load_settings()
        n = apply_all(s, print)
        save_settings(s)
        print(f"Applied to {n} target(s).")
        return
    if "--start-widgets" in args:
        s = load_settings()
        if "--now" not in args:
            time.sleep(4)   # give Plasma a moment after login
        start_autostart(s)
        return
    app = QApplication(sys.argv)
    app.setApplicationName("ThemeForge")
    app.setDesktopFileName("themeforge")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
