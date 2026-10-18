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

from PySide6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QFontDatabase,
                           QFontMetricsF, QGradient, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QSplitter, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

VERSION = "2.1.0"
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
    "network":    ("Network", [F("label", "text", "Label", "Net"),
                               F("iface", "text", "Interface (blank = auto)", ""),
                               F("style", "choice", "Style", "graph", ["graph", "text"]),
                               F("role", "role", "Color", "accent2")]),
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
        return f"${{{var} 28,0 {hx(role)} {hx('accent2' if role != 'accent2' else 'accent')}}}"

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
        out = [kv(f"{b['label']} ↓", f"${{downspeed {I}}}")]
        if b["style"] == "graph":
            out.append(graph(f"downspeedgraph {I}", b["role"]))
        out.append(kv(f"{b['label']} ↑", f"${{upspeed {I}}}"))
        if b["style"] == "graph":
            out.append(graph(f"upspeedgraph {I}", b["role"]))
        return out
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


def write_widget(w, p):
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
        rows = [("kv", f"{b['label']} ↓", "1.4MiB", "muted", "foreground")]
        if b["style"] == "graph":
            rows.append(("graph", 3, b["role"]))
        rows.append(("kv", f"{b['label']} ↑", "86KiB", "muted", "foreground"))
        if b["style"] == "graph":
            rows.append(("graph", 4, b["role"]))
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
#  Music visualizers (drawn by ThemeForge, audio data from cava)
# ════════════════════════════════════════════════════════════════════

VIS_DIR = CFG_DIR / "visualizers"
VIS_STYLES = [("bars", "Bars"), ("mirror", "Mirrored bars"), ("blocks", "LED blocks"),
              ("wave", "Wave"), ("mirrorwave", "Mirrored wave"), ("radial", "Radial ring")]
VIS_COLORS = [("gradient", "Palette gradient"), ("accent", "Accent"), ("accent2", "Second accent"),
              ("foreground", "Text"), ("red", "Red"), ("green", "Green"), ("yellow", "Yellow"),
              ("blue", "Blue"), ("magenta", "Magenta"), ("cyan", "Cyan")]
VIS_TEMPLATES = [("bottom", "Bars along the bottom"), ("center", "Mirrored bars, centered"),
                 ("radial", "Radial ring"), ("wave", "Wave"), ("mirrorwave", "Mirrored wave"),
                 ("led", "LED meter")]


def vis_template(kind="bottom"):
    v = {"id": uuid.uuid4().hex[:8], "name": "Visualizer", "style": "bars", "bars": 64, "gap": 25,
         "rounded": True, "stereo": False, "flip": False, "color": "gradient", "opacity": 90,
         "smoothing": 77, "framerate": 60, "alignment": "bottom_middle", "gap_x": 0, "gap_y": 0,
         "width": 0, "height": 160, "screen": "", "x11": True, "autostart": False}
    presets = {
        "bottom": dict(name="Bottom bars", bars=96, gap=30, height=150, opacity=85),
        "center": dict(name="Center bars", style="mirror", bars=72, width=1100, height=260,
                       alignment="middle_middle", stereo=True),
        "radial": dict(name="Radial ring", style="radial", bars=96, gap=35, width=440, height=440,
                       alignment="middle_right", gap_x=120, stereo=True),
        "wave": dict(name="Wave", style="wave", bars=48, height=200, opacity=80),
        "mirrorwave": dict(name="Mirrored wave", style="mirrorwave", bars=48, width=1000, height=180,
                           alignment="top_middle", gap_y=80, stereo=True),
        "led": dict(name="LED meter", style="blocks", bars=24, gap=28, width=480, height=170,
                    alignment="bottom_left", gap_x=40, gap_y=60, rounded=False),
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


def vis_geometry(v, g):
    """Where visualizer v sits inside screen rect g (QRectF)."""
    W = g.width() if v["width"] <= 0 else min(v["width"], g.width())
    H = min(v["height"], g.height())
    vert, horiz = v["alignment"].split("_")
    gx, gy = v["gap_x"], v["gap_y"]
    x = {"left": g.left() + gx, "middle": g.left() + (g.width() - W) / 2 + gx,
         "right": g.left() + g.width() - W - gx}[horiz]
    y = {"top": g.top() + gy, "middle": g.top() + (g.height() - H) / 2 + gy,
         "bottom": g.top() + g.height() - H - gy}[vert]
    return QRectF(x, y, W, H)


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


def paint_visualizer(qp, rect, vals, v, p):
    n = len(vals)
    if not n or rect.width() < 4 or rect.height() < 4:
        return
    cols = list(p["gradient"]) if v["color"] == "gradient" else [role_color(p, v["color"])]
    style, flip = v["style"], v["flip"]
    L, T, W, H = rect.left(), rect.top(), rect.width(), rect.height()
    slot = W / n
    bw = max(1.0, slot * (1 - v["gap"] / 100))
    base_op = clamp(v["opacity"] / 100)
    qp.save()
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setOpacity(base_op)
    qp.setPen(Qt.NoPen)

    def box(r, rad):
        if rad > 0.5:
            qp.drawRoundedRect(r, rad, rad)
        else:
            qp.drawRect(r)

    if style == "radial":
        cx, cy = rect.center().x(), rect.center().y()
        R = min(W, H) / 2
        r0 = R * 0.42
        lmax = R - r0 - 2
        grad = QRadialGradient(QPointF(0, 0), R)
        _stops(grad, cols, start=r0 / R)
        qp.translate(cx, cy)
        qp.setOpacity(base_op * 0.45)
        qp.setPen(QPen(QColor(cols[0]), 1.5))
        qp.setBrush(Qt.NoBrush)
        qp.drawEllipse(QPointF(0, 0), r0 - 5, r0 - 5)
        qp.setOpacity(base_op)
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
        fill = QPainterPath(line)
        fill.lineTo(L + W, edge)
        fill.lineTo(L, edge)
        fill.closeSubpath()
        qp.setOpacity(base_op * 0.65)
        qp.drawPath(fill)
        qp.setOpacity(base_op)
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(cols[-1]), 2.2))
        qp.drawPath(line)
    elif style == "mirrorwave":
        top = [QPointF(L + (i + 0.5) * slot, cy - val * H / 2) for i, val in enumerate(vals)]
        top = [QPointF(L, cy)] + top + [QPointF(L + W, cy)]
        bottom = [QPointF(pt.x(), 2 * cy - pt.y()) for pt in reversed(top)]
        shape = _smooth_path(top + bottom[1:])
        shape.closeSubpath()
        qp.setOpacity(base_op * 0.6)
        qp.drawPath(shape)
        qp.setOpacity(base_op)
        qp.setBrush(Qt.NoBrush)
        qp.setPen(QPen(QColor(cols[-1]), 1.8))
        qp.drawPath(shape)
    qp.restore()


def vis_pids(vid=None):
    try:
        out = subprocess.run(["pgrep", "-af", "themeforge"], capture_output=True, text=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = line.split()
        if "--visualizer" in parts:
            i = parts.index("--visualizer")
            if i + 1 < len(parts) and (vid is None or parts[i + 1] == vid):
                pids.append(int(parts[0]))
    return [pid for pid in pids if pid != os.getpid()]


def start_visualizer(v):
    if not shutil.which("cava"):
        return False
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if v.get("x11", True):
        env["QT_QPA_PLATFORM"] = "xcb"      # XWayland lets the window place itself
    log = open(VIS_DIR / f"{v['id']}.log", "w")
    subprocess.Popen([sys.executable, str(SCRIPT), "--visualizer", v["id"]], env=env,
                     stdout=log, stderr=log, start_new_session=True)
    log.close()
    return True


def stop_visualizer(vid):
    for pid in vis_pids(vid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


class VisualizerWindow(QWidget):
    """Frameless, click-through desktop window that draws cava's output."""

    def __init__(self, vid):
        super().__init__()
        self.vid = vid
        self.vals = []
        self.v = None
        self.pal = None
        self.mtime = 0
        self.cava_key = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(f"themeforge-vis-{vid}")
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self.on_data)
        self.proc.finished.connect(lambda *_: QTimer.singleShot(2000, self.start_cava))
        self.buf = b""
        if not self.reload():
            raise SystemExit(f"No visualizer with id {vid}")
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.reload)
        self.poll.start()

    def reload(self):
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
        except FileNotFoundError:
            return False
        if mtime == self.mtime:
            return True
        self.mtime = mtime
        s = load_settings()
        v = next((normalize_vis(x) for x in s.get("visualizers", []) if x.get("id") == self.vid), None)
        if v is None:
            QApplication.quit()
            return False
        self.v = v
        self.pal = s.get("visualizers_palette") or s["palette"]
        key = (vis_bar_count(v), v["smoothing"], v["stereo"], v["framerate"])
        if key != self.cava_key:
            self.cava_key = key
            VIS_DIR.mkdir(parents=True, exist_ok=True)
            (VIS_DIR / f"{self.vid}.cava").write_text(cava_raw_config(v))
            self.restart_cava()
        self.place()
        self.update()
        return True

    def place(self):
        screens = QGuiApplication.screens()
        scr = next((s for s in screens if s.name() == self.v["screen"]), QGuiApplication.primaryScreen())
        r = vis_geometry(self.v, QRectF(scr.availableGeometry())).toRect()
        self.setGeometry(r)

    def restart_cava(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.blockSignals(True)
            self.proc.kill()
            self.proc.waitForFinished(1000)
            self.proc.blockSignals(False)
        self.start_cava()

    def start_cava(self):
        if self.proc.state() == QProcess.NotRunning:
            self.buf = b""
            self.proc.start("cava", ["-p", str(VIS_DIR / f"{self.vid}.cava")])

    def on_data(self):
        self.buf += bytes(self.proc.readAllStandardOutput())
        if b"\n" not in self.buf:
            return
        *lines, self.buf = self.buf.split(b"\n")
        vals = parse_cava_frame(lines[-1].decode(errors="ignore"))
        if vals is not None:
            self.vals = vals
            self.update()

    def paintEvent(self, e):
        if not self.v or not self.vals:
            return
        qp = QPainter(self)
        paint_visualizer(qp, QRectF(self.rect()), self.vals, self.v, self.pal)
        qp.end()

    def shutdown(self):
        self.proc.blockSignals(True)
        self.proc.kill()
        self.proc.waitForFinished(1000)


def run_visualizer(vid):
    if vis_pids(vid):
        return          # already running
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ThemeForge visualizer")
    win = VisualizerWindow(vid)
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


def apply_kde(p, s, log):
    current = ini_get(HOME / ".config" / "kdeglobals", "General", "ColorScheme")
    if current and not current.startswith("ThemeForge") and not s.get("kde_original_scheme"):
        s["kde_original_scheme"] = current
    # Plasma ignores re-applying the scheme that's already active, so alternate between two names
    name = "ThemeForgeB" if current == "ThemeForgeA" else "ThemeForgeA"
    d = HOME / ".local" / "share" / "color-schemes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.colors").write_text(kde_colors(p, name))
    ok = run_cmd(["plasma-apply-colorscheme", name], log)
    log(("✓" if ok else "✗") + " KDE Plasma - color scheme " + ("applied" if ok else "written but not applied"))


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


def apply_visualizers(p, s, log):
    # running visualizers watch the settings file and pick this palette up within a second
    s["visualizers_palette"] = copy.deepcopy(p)
    running = sum(bool(vis_pids(v["id"])) for v in s.get("visualizers", []))
    log(f"✓ Visualizers - new colors handed to {running} running visualizer(s)")


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


TARGETS = [
    ("kitty", "kitty", "Writes themeforge.conf, includes it from kitty.conf, live-reloads open windows", "kitty", apply_kitty),
    ("cava", "cava", "Rewrites the [color] section with your gradient and live-reloads", "cava", apply_cava),
    ("kde", "KDE Plasma", "Color scheme for apps, panels and title bars (GTK apps on Breeze follow it too)",
     "plasma-apply-colorscheme", apply_kde),
    ("konsole", "Konsole", "Color scheme, set on your default profile", "konsole", apply_konsole),
    ("widgets", "ThemeForge widgets", "Regenerates the widgets you built with the new colors", "conky", apply_widgets),
    ("visualizers", "Music visualizers", "Running desktop visualizers switch to the new colors", "cava",
     apply_visualizers),
    ("conky", "Other conky configs", "Recolors conky files you added on the Widgets tab (opt-in per file)", "conky",
     apply_external_conky),
    ("wallpaper", "Wallpaper", "Sets the image you picked on the Colors tab", "plasma-apply-wallpaperimage",
     apply_wallpaper),
]


def apply_all(s, log):
    p, done = s["palette"], 0
    for key, name, _desc, exe, fn in TARGETS:
        if not s["targets"].get(key):
            continue
        if exe and not shutil.which(exe):
            log(f"- {name} - skipped, {exe} isn't installed")
            continue
        try:
            fn(p, s, log)
            done += 1
        except Exception as e:
            log(f"✗ {name} - failed: {e}")
    return done


def restore_originals(s, log):
    if not ORIG_DIR.exists():
        log("Nothing to restore - ThemeForge hasn't changed any of your files yet.")
        return
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
    orig = s.pop("kde_original_scheme", None)
    if orig:
        run_cmd(["plasma-apply-colorscheme", orig], log)
        log(f"   KDE color scheme back to {orig}")
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


def default_settings():
    return {"palette": copy.deepcopy(PRESETS["Catppuccin Mocha"]),
            "targets": {key: key in ("kitty", "cava", "kde", "widgets", "visualizers") for key, *_ in TARGETS},
            "wallpaper": "",
            "widgets": [widget_template("clock"), widget_template("system")],
            "visualizers": [vis_template("bottom")],
            "external_conky": detect_conky_files(),
            "check_updates": True,
            "last_update_check": 0,
            "skip_version": ""}


def load_settings():
    s = default_settings()
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        targets = s["targets"]
        s.update(data)
        targets.update(data.get("targets", {}))
        s["targets"] = targets
        if not valid_palette(s["palette"]):
            s["palette"] = copy.deepcopy(PRESETS["Catppuccin Mocha"])
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"ThemeForge: couldn't read settings ({e}); using defaults", file=sys.stderr)
    s["widgets"] = [normalize_widget(w) for w in s.get("widgets", [])]
    s["visualizers"] = [normalize_vis(v) for v in s.get("visualizers", [])]
    return s


def save_settings(s):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(SETTINGS_FILE)


def update_autostart(s):
    wanted = (any(w.get("autostart") for w in s["widgets"])
              or any(e.get("autostart") for e in s.get("external_conky", []))
              or any(v.get("autostart") for v in s.get("visualizers", [])))
    if wanted:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=ThemeForge widgets & visualizers\n"
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
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {mix(line, fg, 0.35)};
                           border-radius: 4px; background: {view}; }}
    QCheckBox::indicator:checked {{ background: {ac}; border-color: {ac}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {line}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {mu}; }}
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
        return 0

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
            m.addAction(label).triggered.connect(lambda *_, k=key: self.add_widget(k))
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
            m.addAction(title).triggered.connect(lambda *_, k=key: self.add_block(k))
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
                        wdg.addItem("US (°F)" if o == "us" else o.capitalize(), o)
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
        self.t = 0.0
        self.setMinimumSize(380, 260)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)

    def set_data(self, v, p, wallpaper):
        self.v, self.pal = v, p
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
        g = vis_geometry(self.v, sg)
        vr = QRectF(sr.left() + g.left() * k, sr.top() + g.top() * k, g.width() * k, g.height() * k)
        qp.setPen(QPen(QColor(mix(p["foreground"], p["background"], 0.4)), 1, Qt.DotLine))
        qp.drawRect(vr)
        n = vis_bar_count(self.v)
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
            ("opacity", "int", "Opacity", (5, 100, " %")),
            ("smoothing", "int", "Smoothing", (0, 100, " %")),
            ("framerate", "int", "Frame rate", (10, 144, " fps")),
        ]),
        ("Placement", [
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
            m.addAction(label).triggered.connect(lambda *_, k=key: self.add(k))
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
            if kind == "screen":
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
        self.preview.set_data(self.cur, self.win.pal, self.win.settings.get("wallpaper"))

    def select(self, row):
        self.cur = self.items[row] if 0 <= row < len(self.items) else None
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
        self.refresh_preview()
        self.win.schedule_save()

    def add(self, kind):
        self.items.append(vis_template(kind))
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


# ── Targets tab ────────────────────────────────────────────────────

class TargetsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        gb = QGroupBox("What “Apply to desktop” changes")
        g = QGridLayout(gb)
        g.setColumnStretch(1, 1)
        self.checks = {}
        for i, (key, name, desc, exe, _fn) in enumerate(TARGETS):
            cb = QCheckBox(name)
            cb.setStyleSheet("font-weight: bold;")
            cb.toggled.connect(lambda on, k=key: self.toggle(k, on))
            self.checks[key] = cb
            found = shutil.which(exe) is not None
            st = QLabel("installed" if found else f"{exe} not found")
            st.setObjectName("muted")
            g.addWidget(cb, i, 0)
            g.addWidget(hint_label(desc), i, 1)
            g.addWidget(st, i, 2)
        v.addWidget(gb)
        row = QHBoxLayout()
        b_apply = QPushButton("Apply to desktop")
        b_apply.setObjectName("primary")
        b_apply.clicked.connect(self.win.apply_desktop)
        b_restore = QPushButton("Restore my original files…")
        b_restore.clicked.connect(self.restore)
        b_folder = QPushButton("Open ThemeForge folder")
        b_folder.clicked.connect(lambda *_: subprocess.Popen(["xdg-open", str(CFG_DIR)]))
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
            "Before changing kitty.conf, cava's config, konsolerc or a conky file for the first time, "
            f"ThemeForge copies the original into {ORIG_DIR}. “Restore” puts those back."))

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

    def refresh(self):
        for key, cb in self.checks.items():
            cb.blockSignals(True)
            cb.setChecked(bool(self.win.settings["targets"].get(key)))
            cb.blockSignals(False)
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
        top.addWidget(b_save)
        top.addWidget(self.b_del)
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
        self.targets_tab = TargetsTab(self)
        self.tabs.addTab(self.colors_tab, "Colors")
        self.tabs.addTab(self.widgets_tab, "Widgets")
        self.tabs.addTab(self.vis_tab, "Visualizers")
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

        self.populate_presets(self.pal.get("name"))
        self.restyle()
        self.colors_tab.refresh()
        self.widgets_tab.refresh()
        self.vis_tab.refresh()
        self.targets_tab.refresh()
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
        if self.pal.get("name") in PRESETS or self.pal.get("name") in self.user_theme_names():
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

    def palette_changed(self):
        self.colors_tab.preview.set_palette(self.pal)
        self.widgets_tab.refresh_preview()
        self.vis_tab.refresh_preview()
        self.widgets_tab.build_block_form()
        self.qss_timer.start()
        self.schedule_save()

    def restyle(self):
        QApplication.instance().setStyleSheet(app_qss(self.pal))

    # ── presets / saved themes
    def user_theme_names(self):
        return [f.stem for f in sorted(THEMES_DIR.glob("*.json"))] if THEMES_DIR.exists() else []

    def populate_presets(self, select=None):
        box = self.preset_box
        box.blockSignals(True)
        box.clear()
        for name in PRESETS:
            box.addItem(name, ("builtin", name))
        users = self.user_theme_names()
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
                p = json.loads((THEMES_DIR / f"{name}.json").read_text())
                p["name"] = name
            except Exception as e:
                QMessageBox.warning(self, "ThemeForge", f"Couldn't load that theme: {e}")
                return
            if not valid_palette(p):
                QMessageBox.warning(self, "ThemeForge", "That theme file is missing some colors.")
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
        for v in self.settings.get("visualizers", []):   # running visualizers use the old code
            if vis_pids(v["id"]):
                stop_visualizer(v["id"])
                start_visualizer(v)
        os.execv(sys.executable, [sys.executable, str(SCRIPT)])

    def schedule_save(self):
        self.save_timer.start()

    def save_now(self):
        try:
            save_settings(self.settings)
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
    if "--visualizer" in args:
        i = args.index("--visualizer")
        if i + 1 < len(args):
            run_visualizer(args[i + 1])
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
