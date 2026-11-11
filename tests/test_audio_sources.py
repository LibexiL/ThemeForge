"""Tests for choosing what a visualizer listens to (2.9)."""
import sys
import time
import types

import pytest


class P:
    """A fake psutil.Process."""
    def __init__(self, pid, name, ppid):
        self.pid, self._name, self._ppid = pid, name, ppid

    def name(self):
        return self._name

    def ppid(self):
        return self._ppid


PROCS = [P(4, "System", 0), P(100, "explorer.exe", 4), P(200, "chrome.exe", 100), P(201, "chrome.exe", 200),
         P(202, "chrome.exe", 200), P(300, "Discord.exe", 100), P(301, "Discord.exe", 300),
         P(400, "Game.exe", 100), P(500, "spotify.exe", 100), P(600, "chrome.exe", 100)]
BY_PID = {p.pid: p for p in PROCS}


def test_app_names_and_source(tf, monkeypatch):
    assert tf.app_names("Discord.exe, chrome;\n Spotify, discord") == ["discord", "chrome", "spotify"]
    monkeypatch.setattr(tf, "AUDIO_MODES", tf.AUDIO_MODES + [("apps", "x"), ("except", "y")])
    assert tf.audio_source({"audio_mode": "except", "audio_device": "X", "audio_apps": "Discord"}) == \
        ("except", "", ("discord",))
    assert tf.audio_source({"audio_mode": "output", "audio_device": "Headphones", "audio_apps": "a"}) == \
        ("output", "Headphones", ())
    assert tf.audio_source({"audio_mode": "bogus"}) == ("default", "", ())
    assert tf.audio_source(tf.vis_template()) == ("default", "", ())


def test_process_roots_and_blocking(tf):
    assert tf.process_roots(["chrome"], PROCS) == [200, 600]          # two separate chrome trees, not the children
    assert tf.process_roots(["discord", "nope"], PROCS) == [300]
    assert tf.blocked_by(202, {"chrome"}, BY_PID) and tf.blocked_by(301, {"discord"}, BY_PID)
    assert not tf.blocked_by(500, {"chrome"}, BY_PID)


def test_capture_plans(tf):
    def plan(mode, apps=(), device="", sessions=(201, 301, 400, 500)):
        return tf.capture_plan((mode, device, tuple(apps)), lambda n: tf.process_roots(n, PROCS),
                               lambda: list(sessions), BY_PID, self_pid=9999)
    assert plan("default") == ("device", "output", "")
    assert plan("output", device="Headphones") == ("device", "output", "Headphones")
    assert plan("input", device="Mic") == ("device", "input", "Mic")
    assert plan("apps", ["spotify", "chrome"]) == ("include", (200, 500, 600))
    assert plan("apps", ["notrunning"]) == ("include", ())
    assert plan("except", ["discord"]) == ("exclude", 300)            # one app: Windows leaves it out itself
    assert plan("except", ["notrunning"]) == ("exclude", 9999)        # nothing to block: all but ThemeForge
    assert plan("except", ["chrome"]) == ("include", (301, 400, 500))  # two chrome trees: every other app
    assert plan("except", ["discord", "game"]) == ("include", (201, 500))


def test_cava_listens_to_the_chosen_source(tf, monkeypatch):
    monkeypatch.setattr(tf, "IS_WINDOWS", False)
    v = dict(tf.vis_template(), source=("output", "Built-in Audio  (alsa_output.pci.analog-stereo.monitor)", ()))
    cfg = tf.cava_raw_config(v)
    assert "[input]\nmethod = pulse\nsource = alsa_output.pci.analog-stereo.monitor" in cfg
    assert "[input]" not in tf.cava_raw_config(dict(tf.vis_template(), source=("default", "", ())))
    assert "[input]" not in tf.cava_raw_config(tf.vis_template())


def test_linux_device_list(tf, monkeypatch):
    out = ("Source #1\n\tState: RUNNING\n\tName: alsa_output.pci.analog-stereo.monitor\n"
           "\tDescription: Monitor of Built-in Audio\n\nSource #2\n\tName: alsa_input.usb-mic.mono\n"
           "\tDescription: USB Microphone\n")
    monkeypatch.setattr(tf, "IS_WINDOWS", False)
    monkeypatch.setattr(tf.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=out))
    d = tf.audio_devices()
    assert d["output"] == ["Monitor of Built-in Audio  (alsa_output.pci.analog-stereo.monitor)"]
    assert d["input"] == ["USB Microphone  (alsa_input.usb-mic.mono)"]
    assert tf.device_id(d["input"][0]) == "alsa_input.usb-mic.mono"


def fake_pyaudio(monkeypatch):
    devs = [{"index": 0, "name": "Speakers (Realtek)", "hostApi": 1, "maxInputChannels": 0},
            {"index": 1, "name": "Speakers (Realtek) [Loopback]", "hostApi": 1, "maxInputChannels": 2,
             "isLoopbackDevice": True, "defaultSampleRate": 48000.0},
            {"index": 2, "name": "Headphones (USB) [Loopback]", "hostApi": 1, "maxInputChannels": 2,
             "isLoopbackDevice": True, "defaultSampleRate": 44100.0},
            {"index": 3, "name": "Microphone (USB)", "hostApi": 1, "maxInputChannels": 1,
             "defaultSampleRate": 48000.0},
            {"index": 4, "name": "Microphone (MME)", "hostApi": 0, "maxInputChannels": 1}]

    class PyAudio:
        def get_host_api_info_by_type(self, t):
            return {"index": 1, "defaultInputDevice": 3}

        def get_device_count(self):
            return len(devs)

        def get_device_info_by_index(self, i):
            return devs[i]

        def get_default_wasapi_loopback(self):
            return devs[1]

        def terminate(self):
            pass
    mod = types.ModuleType("pyaudiowpatch")
    mod.PyAudio, mod.paWASAPI = PyAudio, 13
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", mod)
    return PyAudio()


def test_windows_devices(tf, monkeypatch):
    pa = fake_pyaudio(monkeypatch)
    monkeypatch.setattr(tf, "IS_WINDOWS", True)
    assert tf.audio_devices() == {"output": ["Speakers (Realtek)", "Headphones (USB)"],
                                  "input": ["Microphone (USB)"]}
    find = tf.LoopbackFeed.find_device
    assert find(pa, "output", "Headphones (USB)")["index"] == 2
    assert find(pa, "output", "")["index"] == 1
    assert find(pa, "output", "Unplugged")["index"] == 1                 # falls back to the default
    assert find(pa, "input", "")["index"] == 3 and find(pa, "input", "Microphone (USB)")["index"] == 3
    with pytest.raises(RuntimeError):
        find(pa, "input", "Missing mic")


def test_app_capture_mixes_and_follows_apps(tf, monkeypatch, qapp):
    np = pytest.importorskip("numpy")
    procs = list(PROCS)
    opened, closed = [], []

    class FakeLoopback:
        RATE, CHANNELS = 44100, 2

        def __init__(self, pid, exclude=False):
            opened.append((pid, exclude))
            self.pid, self.t0, self.n = pid, time.monotonic(), 0

        def read(self):
            n = int((time.monotonic() - self.t0) * self.RATE) - self.n
            idx = np.arange(self.n, self.n + n) / self.RATE
            self.n += n
            x = (0.2 * np.sin(2 * np.pi * 440 * idx)).astype(np.float32)
            return np.repeat(x[:, None], 2, axis=1)

        def close(self):
            closed.append(self.pid)
    monkeypatch.setattr(tf, "ProcessLoopback", FakeLoopback)
    monkeypatch.setattr(tf, "_session_pids", lambda: [201, 400, 500])
    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(process_iter=lambda attrs=None: list(procs)))
    monkeypatch.setitem(sys.modules, "comtypes", types.SimpleNamespace(COINIT_MULTITHREADED=0,
                                                                        CoInitializeEx=lambda flags=0: None))
    monkeypatch.setattr(tf.LoopbackFeed, "SCAN_EVERY", 0.2)
    feed = tf.LoopbackFeed("test")
    frames = []
    feed.frame.connect(frames.append)
    feed.configure(24, 60, 77, False, ("apps", "", ("chrome", "spotify")))

    def wait(cond, t=5.0):
        end = time.monotonic() + t
        while time.monotonic() < end and not cond():
            qapp.processEvents()
            time.sleep(0.01)
        return cond()
    try:
        assert wait(lambda: len(frames) > 15 and max(frames[-1]) > 0.3)
        assert sorted(opened) == [(200, False), (500, False), (600, False)]
        procs[:] = [p for p in procs if p.pid != 600]                       # one chrome window quits
        assert wait(lambda: 600 in closed)
        feed.configure(24, 60, 77, False, ("except", "", ("discord",)))     # block Discord instead
        assert wait(lambda: (300, True) in opened)
    finally:
        feed.stop()
    assert all(len(f) == 24 for f in frames)


def test_visualizer_tab_audio_controls(tf, home, qapp, monkeypatch):
    monkeypatch.setattr(tf, "audio_devices", lambda: {"output": ["Headphones"], "input": ["Mic"]})
    s = tf.load_settings()
    s["visualizers"] = [tf.vis_template("bottom")]
    tf.save_settings(s)
    w = tf.MainWindow()
    try:
        tab = w.vis_tab
        tab.refresh()
        tab.select(0)
        assert not tab.inputs["audio_device"].isEnabled()
        assert ("audio_apps" in tab.inputs) == (sys.platform == "win32")
        tab.inputs["audio_mode"].setCurrentIndex(tab.inputs["audio_mode"].findData("output"))
        assert tab.cur["audio_mode"] == "output" and tab.inputs["audio_device"].isEnabled()
        box = tab.inputs["audio_device"]
        assert [box.itemData(i) for i in range(box.count())] == ["", "Headphones"]
        box.setCurrentIndex(1)
        assert tab.cur["audio_device"] == "Headphones"
        assert tf.audio_source(tab.cur) == ("output", "Headphones", ())
    finally:
        w.close()
