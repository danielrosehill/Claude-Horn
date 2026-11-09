"""Claude-Horn desktop client: tray icon, on/off toggle, MQTT subscriber, horn player.

Config: ~/.config/claude-horn/client.json
  {"name": "desktop", "mqtt": {"host": "...", "port": 1883, "username": "...", "password": "..."},
   "base_topic": "claude-horn", "enabled": true, "sounds_dir": "~/.local/share/claude-horn/sounds",
   "tts": {"enabled": true, "voice": "en-GB-RyanNeural"}}

Speech: a toot carrying "say" is spoken after the horn. The text is synthesised here, on the
client, with edge-tts (Microsoft's online neural voices; needs internet, no key, light on CPU).
Clips are cached in ~/.cache/claude-horn/tts/ by text+voice, so ladder repeats don't re-fetch.
If synthesis fails, the horn still plays.
"""
import asyncio
import hashlib
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

CONFIG_PATH = Path(os.environ.get("CLAUDE_HORN_CLIENT_CONFIG", "~/.config/claude-horn/client.json")).expanduser()
DEFAULTS = {
    "name": socket.gethostname(),
    "mqtt": {"host": "localhost", "port": 1883, "username": None, "password": None},
    "base_topic": "claude-horn",
    "enabled": True,
    "sounds_dir": "~/.local/share/claude-horn/sounds",
    "tts": {"enabled": True, "voice": "en-GB-RyanNeural"},
}
SOUND_DIRS = ("horns", "bugles", "herman", "chaos")
TTS_CACHE = Path("~/.cache/claude-horn/tts").expanduser()


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text())
        for k, v in user.items():
            cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def save_enabled(enabled):
    data = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    data["enabled"] = enabled
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")


def find_sound(sounds_dir, name):
    for sub in SOUND_DIRS:
        p = sounds_dir / sub / f"{name}.mp3"
        if p.exists():
            return p
    return None


def play(paths):
    """Play files back to back without blocking the UI."""
    player = next((p for p in ("ffplay", "mpv", "pw-play", "paplay") if shutil.which(p)), None)
    if not player or not paths:
        return
    if player == "ffplay":
        cmds = [["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(p)] for p in paths]
    elif player == "mpv":
        cmds = [["mpv", "--no-video", "--really-quiet", *map(str, paths)]]
    else:
        cmds = [[player, str(p)] for p in paths]
    script = " && ".join(" ".join(f"'{a}'" for a in c) for c in cmds)
    subprocess.Popen(["sh", "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synthesise(text, voice):
    """Speak text to an MP3 with edge-tts; return the path, or None if it failed."""
    out = TTS_CACHE / f"{hashlib.sha1(f'{voice}|{text}'.encode()).hexdigest()[:16]}.mp3"
    if out.exists() and out.stat().st_size:
        return out
    try:
        import edge_tts
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(out)), timeout=20))
        return out if out.exists() and out.stat().st_size else None
    except Exception as e:  # network down, bad voice name, edge-tts missing
        print(f"claude-horn: tts failed: {e}", file=sys.stderr)
        out.unlink(missing_ok=True)
        return None


def play_with_speech(clips, text, voice):
    """Synthesise (off the UI thread), then play the clips followed by the speech."""
    def run():
        speech = synthesise(text, voice) if text else None
        play(clips + ([speech] if speech else []))
    threading.Thread(target=run, daemon=True).start()


def icon(color):
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor("#222"))
    # A horn: bell (circle) + tube (triangle-ish polygon).
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF([QPointF(6, 26), QPointF(6, 38), QPointF(44, 56), QPointF(44, 8)]))
    p.drawEllipse(38, 6, 22, 52)
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    tooted = Signal(dict)
    connected = Signal(bool)


class HornClient:
    def __init__(self, app):
        self.app = app
        self.cfg = load_config()
        self.name = self.cfg["name"]
        self.base = self.cfg["base_topic"]
        self.enabled = bool(self.cfg["enabled"])
        self.sounds = Path(self.cfg["sounds_dir"]).expanduser()
        self.pending = None  # last toot id not yet acknowledged
        self.online = False

        self.icons = {"on": icon("#f5b301"), "off": icon("#888888"), "alert": icon("#e0312b"), "down": icon("#444444")}
        self.tray = QSystemTrayIcon(self.icons["on"])
        self.tray.setToolTip(f"Claude-Horn ({self.name})")
        menu = QMenu()
        self.toggle = QAction("Horn enabled", checkable=True, checked=self.enabled)
        self.toggle.toggled.connect(self.set_enabled)
        self.ack_action = QAction("I'm here (acknowledge)", enabled=False)
        self.ack_action.triggered.connect(lambda: self.ack("menu"))
        test = QAction("Test horn", triggered=lambda: play([find_sound(self.sounds, "bugle")]))
        test_say = QAction("Test speech", triggered=lambda: play_with_speech(
            [], f"Claude-Horn on {self.name} can talk.", self.tts_voice()))
        quit_ = QAction("Quit", triggered=self.quit)
        for a in (self.toggle, self.ack_action, test, test_say):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activated)
        self.tray.messageClicked.connect(lambda: self.ack("notification"))
        self.tray.show()

        self.bridge = Bridge()
        self.bridge.tooted.connect(self.on_toot)
        self.bridge.connected.connect(self.on_connected)
        self.blink = QTimer(interval=500, timeout=self._blink)
        self._blink_on = False

        m = self.cfg["mqtt"]
        self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"claude-horn-{self.name}-{os.getpid()}")
        if m.get("username"):
            self.mq.username_pw_set(m["username"], m.get("password"))
        self.mq.will_set(self.topic("state"), json.dumps({"online": False}), qos=1, retain=True)
        self.mq.on_connect = lambda c, u, f, rc, p=None: self._mq_connected(rc)
        self.mq.on_disconnect = lambda *a: self.bridge.connected.emit(False)
        self.mq.on_message = lambda c, u, msg: self.bridge.tooted.emit(json.loads(msg.payload or b"{}"))
        self.mq.reconnect_delay_set(2, 60)
        self.mq.connect_async(m["host"], int(m["port"]))
        self.mq.loop_start()
        self.refresh_icon()

    def tts_voice(self, requested=None):
        return requested or self.cfg["tts"].get("voice") or "en-GB-RyanNeural"

    def topic(self, kind):
        return f"{self.base}/{self.name}/{kind}"

    def _mq_connected(self, rc):
        self.mq.subscribe(self.topic("toot"), qos=1)
        self.publish_state()
        self.bridge.connected.emit(True)

    def publish_state(self):
        self.mq.publish(self.topic("state"), json.dumps({"online": True, "enabled": self.enabled, "ts": time.time()}),
                        qos=1, retain=True)

    def on_connected(self, ok):
        self.online = ok
        self.refresh_icon()

    def refresh_icon(self):
        if self.pending:
            return
        key = "down" if not self.online else ("on" if self.enabled else "off")
        self.tray.setIcon(self.icons[key])
        state = "offline" if not self.online else ("on" if self.enabled else "off")
        self.tray.setToolTip(f"Claude-Horn ({self.name}): {state}")

    def set_enabled(self, enabled):
        self.enabled = enabled
        save_enabled(enabled)
        self.publish_state()
        self.refresh_icon()

    def on_toot(self, data):
        if not self.enabled:
            return
        horn = find_sound(self.sounds, data.get("horn") or "bugle") or find_sound(self.sounds, "bugle")
        clips = [horn]
        if data.get("chaos"):
            chaos = sorted((self.sounds / "chaos").glob("*.mp3"))
            clips = random.sample(chaos, min(2, len(chaos))) + clips
        clips = [c for c in clips if c]
        say = data.get("say") if self.cfg["tts"].get("enabled", True) else None
        if say:
            play_with_speech(clips, say, self.tts_voice(data.get("voice")))
        else:
            play(clips)
        self.pending = data.get("id")
        self.ack_action.setEnabled(True)
        msg = data.get("message") or "Claude needs you."
        self.tray.showMessage("Claude-Horn", f"{msg}\nClick to acknowledge.", self.icons["alert"], 15000)
        self.blink.start()

    def _blink(self):
        self._blink_on = not self._blink_on
        self.tray.setIcon(self.icons["alert" if self._blink_on else "on"])

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.pending:
                self.ack("tray")
            else:
                self.toggle.toggle()

    def ack(self, how):
        if not self.pending:
            return
        self.mq.publish(self.topic("ack"), json.dumps({"id": self.pending, "ts": time.time(), "how": how}), qos=1)
        self.pending = None
        self.ack_action.setEnabled(False)
        self.blink.stop()
        self.refresh_icon()

    def quit(self):
        self.mq.publish(self.topic("state"), json.dumps({"online": False}), qos=1, retain=True).wait_for_publish(2)
        self.mq.loop_stop()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    client = HornClient(app)
    signal.signal(signal.SIGTERM, lambda *a: client.quit())
    signal.signal(signal.SIGINT, lambda *a: client.quit())
    tick = QTimer(interval=500, timeout=lambda: None)  # let Python handle signals
    tick.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
