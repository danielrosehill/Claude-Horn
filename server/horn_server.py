#!/usr/bin/env python3
"""Claude-Horn server: takes a toot request over HTTP, publishes it to the clients over MQTT,
and escalates (louder horn, more machines) until a client acknowledges.

HTTP API (JSON in, JSON out):
  POST /toot     {"horn": "bugle", "target": "desktop", "escalate": true, "message": "..."}
                 every field optional. escalate=false -> one toot, no ladder.
  POST /ack      {"id": "..."}            stop an escalation from the agent side
  GET  /status   clients (online/enabled) and open escalations
  GET  /horns    horn names the clients ship with
  GET  /health   "ok"

MQTT topics (base topic default "claude-horn"):
  <base>/<client>/toot   server -> client  {"id", "horn", "message", "step", "ts"}
  <base>/<client>/state  client -> all     retained {"online", "enabled", "ts"}; LWT online=false
  <base>/<client>/ack    client -> server  {"id", "ts", "how"}
"""
import json
import logging
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

log = logging.getLogger("claude-horn")
HORNS = ["bugle", "air-horn", "car-horn", "car-horn-long", "ship-horn", "siren"]
CHAOS = ["pa-bell", "hey", "mayday", "glass-break", "cymbal-crash", "alarm-clock", "shout", "grunt"]

DEFAULT_CONFIG = {
    "mqtt": {"host": "localhost", "port": 1883, "username": None, "base_topic": "claude-horn"},
    "http": {"bind": "0.0.0.0", "port": 8787},
    "clients": ["desktop", "laptop"],
    # Each step: which horn, which machines ("primary" = the requested target, "all" = every
    # online+enabled client, or a list of names), and how long to wait for an ack before the
    # next step. The last step's wait is ignored.
    "ladder": [
        {"horn": "bugle", "targets": "primary", "wait": 60},
        {"horn": "air-horn", "targets": "others", "wait": 60},
        {"horn": "air-horn", "targets": "all", "wait": 90},
        {"horn": "ship-horn", "targets": "all", "chaos": True},
    ],
}


def load_config():
    path = Path(os.environ.get("CLAUDE_HORN_CONFIG", "config.json"))
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        user = json.loads(path.read_text())
        for k, v in user.items():
            cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    cfg["mqtt"]["password"] = os.environ.get("MQTT_PASSWORD")
    if os.environ.get("MQTT_HOST"):
        cfg["mqtt"]["host"] = os.environ["MQTT_HOST"]
    if os.environ.get("MQTT_USERNAME"):
        cfg["mqtt"]["username"] = os.environ["MQTT_USERNAME"]
    return cfg


class Horn:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["mqtt"]["base_topic"]
        self.state = {}          # client -> {"online", "enabled", "ts"}
        self.open = {}           # toot id -> {"event", "target", "step", "started", "acked_by"}
        self.lock = threading.Lock()
        self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"claude-horn-server-{uuid.uuid4().hex[:6]}")
        if cfg["mqtt"].get("username"):
            self.mq.username_pw_set(cfg["mqtt"]["username"], cfg["mqtt"].get("password"))
        self.mq.on_connect = self._on_connect
        self.mq.on_message = self._on_message
        self.mq.connect_async(cfg["mqtt"]["host"], int(cfg["mqtt"]["port"]))
        self.mq.loop_start()

    # --- MQTT ---------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, props=None):
        log.info("mqtt connected rc=%s", rc)
        client.subscribe(f"{self.base}/+/state")
        client.subscribe(f"{self.base}/+/ack")

    def _on_message(self, client, userdata, msg):
        try:
            _, name, kind = msg.topic.rsplit("/", 2)
            data = json.loads(msg.payload or b"{}")
        except ValueError:
            return
        if kind == "state":
            with self.lock:
                self.state[name] = data
        elif kind == "ack":
            self.ack(data.get("id"), by=name)

    # --- core ---------------------------------------------------------------
    def available(self):
        with self.lock:
            return [c for c in self.cfg["clients"]
                    if self.state.get(c, {}).get("online") and self.state.get(c, {}).get("enabled", True)]

    def resolve(self, spec, primary):
        live = self.available()
        if spec == "primary":
            # If the primary is off or disabled, fall through to whoever is up.
            return [primary] if primary in live else live[:1]
        if spec == "others":
            return [c for c in live if c != primary] or live
        if spec == "all":
            return live
        return [c for c in spec if c in live]

    def publish(self, client, payload):
        self.mq.publish(f"{self.base}/{client}/toot", json.dumps(payload), qos=1)

    def toot(self, horn=None, target=None, escalate=True, message=None):
        tid = uuid.uuid4().hex[:10]
        target = target or self.cfg["clients"][0]
        if not escalate:
            sent = self.resolve([target] if target != "all" else "all", target)
            for c in sent:
                self.publish(c, {"id": tid, "horn": horn or "bugle", "message": message, "step": 0, "ts": time.time()})
            return {"id": tid, "sent_to": sent, "escalating": False}
        ev = threading.Event()
        with self.lock:
            self.open[tid] = {"event": ev, "target": target, "step": 0, "started": time.time(), "acked_by": None}
        threading.Thread(target=self._ladder, args=(tid, ev, horn, target, message), daemon=True).start()
        return {"id": tid, "escalating": True, "target": target}

    def _ladder(self, tid, ev, first_horn, target, message):
        ladder = self.cfg["ladder"]
        for i, step in enumerate(ladder):
            horn = first_horn if (i == 0 and first_horn) else step["horn"]
            sent = self.resolve(step["targets"], target)
            with self.lock:
                if tid in self.open:
                    self.open[tid]["step"] = i
            payload = {"id": tid, "horn": horn, "message": message, "step": i, "chaos": bool(step.get("chaos")), "ts": time.time()}
            for c in sent:
                self.publish(c, payload)
            log.info("toot %s step %d horn=%s -> %s", tid, i, horn, sent or "nobody online")
            if i == len(ladder) - 1 or ev.wait(step.get("wait", 60)):
                break
        with self.lock:
            self.open.pop(tid, None)

    def ack(self, tid, by="agent"):
        with self.lock:
            entry = self.open.get(tid)
            if entry:
                entry["acked_by"] = by
                entry["event"].set()
        if entry:
            log.info("toot %s acked by %s", tid, by)
        return bool(entry)

    def status(self):
        with self.lock:
            return {
                "clients": {c: self.state.get(c, {"online": False}) for c in self.cfg["clients"]},
                "open": {k: {"target": v["target"], "step": v["step"], "age_s": round(time.time() - v["started"])}
                         for k, v in self.open.items()},
            }


def make_handler(horn):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, "ok")
            if self.path == "/status":
                return self._send(200, horn.status())
            if self.path == "/horns":
                return self._send(200, {"horns": HORNS, "chaos": CHAOS})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                body = self._body()
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/toot":
                h = body.get("horn")
                if h and h not in HORNS + CHAOS:
                    return self._send(400, {"error": f"unknown horn {h}", "horns": HORNS, "chaos": CHAOS})
                return self._send(200, horn.toot(h, body.get("target"), body.get("escalate", True), body.get("message")))
            if self.path == "/ack":
                return self._send(200, {"acked": horn.ack(body.get("id"))})
            self._send(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

    return H


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    horn = Horn(cfg)
    srv = ThreadingHTTPServer((cfg["http"]["bind"], int(cfg["http"]["port"])), make_handler(horn))
    log.info("listening on %s:%s", cfg["http"]["bind"], cfg["http"]["port"])
    srv.serve_forever()


if __name__ == "__main__":
    main()
