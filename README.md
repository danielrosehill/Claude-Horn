# Claude-Horn

When an agent needs you and you're not looking, it toots a horn. If you still
don't answer, it gets a louder horn and tries your other computer.

A stripped-down successor to [Claude-PA](https://github.com/danielrosehill/Claude-PA):
no TTS, no Home Assistant cascade, no phone calls. Just horns over MQTT.

```
agent ──HTTP──▶ horn server (home server, Docker) ──MQTT──▶ tray client on each machine ──▶ 🔊
                      ▲                                            │
                      └──────────────── ack (you clicked) ─────────┘
```

## Parts

| Part | Where it runs | What it does |
|---|---|---|
| `server/` | Home server, Docker | HTTP API → MQTT. Runs the escalation ladder; stops when any client acks. Python stdlib + `paho-mqtt`. |
| `client/` | Each desktop/laptop | Tray icon (PySide6). On/off toggle, plays horns, notification with click-to-acknowledge. **On by default, autostarts at login.** |
| `tools/horn` | Wherever the agent runs | `curl` wrapper the agent calls. |
| `sounds/` | Shipped to clients | `horns/` and `chaos/` MP3s. |

Needs an MQTT broker that the server and the clients can all reach (Mosquitto, or the one Home Assistant already runs).

## Horns

| Name | Source |
|---|---|
| `bugle` | Synthesised ("Charge!") by `tools/synth-horns.py` |
| `air-horn` | Synthesised (three-blast stadium horn) by `tools/synth-horns.py` |
| `car-horn`, `car-horn-long`, `ship-horn`, `siren` | From Claude-PA's `soundfx/` (Pixabay) |

`chaos/` (`pa-bell`, `hey`, `mayday`, `glass-break`, `cymbal-crash`, `alarm-clock`, `shout`, `grunt`) also comes from Claude-PA. A ladder step with `"chaos": true` plays two random chaos clips before the horn. Any of these names can also be sent directly as `horn`.

To add a horn, drop an MP3 into `sounds/horns/`, add its name to `HORNS` in `server/horn_server.py`, and re-run `client/install.sh` on each client.

## Escalation ladder

Default (`server/config.example.json`):

| Step | Horn | Targets | Wait for ack |
|---|---|---|---|
| 0 | bugle (or the requested horn) | `primary`: the requested target | 60 s |
| 1 | air-horn | `others`: every other client | 60 s |
| 2 | air-horn | `all` | 90 s |
| 3 | ship-horn + chaos | `all` | n/a (last step) |

Only clients that are **online and enabled** get tooted. A client publishes a retained `state` message, and its MQTT last-will marks it offline. If the primary is off or disabled, step 0 falls through to the first client that is up.

## MQTT topics

Base topic defaults to `claude-horn`.

| Topic | Direction | Payload |
|---|---|---|
| `claude-horn/<client>/toot` | server → client | `{"id","horn","message","step","chaos","ts"}` |
| `claude-horn/<client>/state` | client → all, retained | `{"online","enabled","ts"}`; LWT `{"online":false}` |
| `claude-horn/<client>/ack` | client → server | `{"id","ts","how"}` |

## HTTP API

| Call | Body | Returns |
|---|---|---|
| `POST /toot` | `{"horn"?, "target"?, "escalate"? (default true), "message"?}` | `{"id", ...}` |
| `POST /ack` | `{"id"}` | `{"acked": bool}` |
| `GET /status` | | client states + open escalations |
| `GET /horns` | | available names |
| `GET /health` | | `"ok"` |

The API has no auth. Bind it to your LAN or tailnet only.

## Install

**Server** (on the home server):

```bash
cd server
cp config.example.json config.json   # set the broker host, user and client names
echo 'MQTT_PASSWORD=...' > .env
docker compose up -d --build
curl localhost:8787/status
```

**Client** (on each machine; needs `uv`, a system tray and `ffplay`, `mpv`, `pw-play` or `paplay`):

```bash
client/install.sh desktop      # the name must match one in the server's "clients"
$EDITOR ~/.config/claude-horn/client.json   # broker host, user, password
~/.local/bin/claude-horn-client &
```

The installer adds `~/.config/autostart/claude-horn.desktop`. Tray: **left-click** toggles on/off (or acknowledges, if a horn is pending). **Right-click** gives the menu: enabled, I'm here, test horn, quit. The on/off state persists in `client.json` and is published to the server, so a disabled machine is skipped, not tooted.

## Agent usage

```bash
export CLAUDE_HORN_URL=http://<server>:8787
horn -m "Waiting on your approval"          # escalating, starts on the default client
horn -t laptop -m "Build failed"            # start on the laptop
horn -H air-horn --once                     # single toot, no ladder
horn --status
```

A line for an agent's instructions file:

> When you are blocked on me and I haven't replied for a few minutes, run `horn -m "<one-line reason>"`. Don't use it for routine progress updates.

## Status (2026-11-09)

- **Tested:** end-to-end on a local broker with two headless clients: ladder timing and targets, agent-side ack, chaos pre-roll, disabled-state handling.
- **Verified live (2026-11-09):** Docker build and server against a real Mosquitto with a password login; tray clients on two KDE Plasma 6 / Wayland machines report online, and a toot plays on the target.
- **Not yet verified:** click-to-ack from the tray or notification, and autostart after a fresh login.
- A git-URL build context (`build: https://…#main:server`) needs BuildKit. On a host without a buildkitd socket, clone the repo and build `./server` instead.
- **Known gap:** there is no automatic "the user came back" detection. KDE Wayland doesn't expose `GetSessionIdleTime` (`org.freedesktop.ScreenSaver` returns `NotSupported`), so the ack is a click on the tray or the notification.

## Licence

Code: MIT. Synthesised horns: CC0. The Claude-PA samples are under the Pixabay Content License.
