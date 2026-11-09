# Claude-Horn

Release tier: small (`v1.0`, `v1.1`, ...).

- Server: `server/horn_server.py` (stdlib HTTP + paho-mqtt). Client: `client/claude_horn_client/__main__.py` (PySide6 tray).
- Topic and API contract: README. Change both sides together.
- Sound names live in `HORNS`/`BUGLES`/`HERMAN`/`CHAOS` in the server and as files in `sounds/<dir>/` (client `SOUND_DIRS`). Keep them in sync.
- Bugles: `tools/synth-horns.py`. Herman clips: rendered once with the MWP Chatterbox production `herman` conditionals via `modal_app/scripts/voice_tune.py`'s `render` (empty refs, `gpu=["L40S","A10G","L4"]`: L4 alone queues), then trimmed and loudnorm'd to MP3. Texts: `sounds/herman/lines.json`.
- Spoken messages: edge-tts on the client (`say` in the toot payload), not on the server.
- Test without a GUI: a local `amqtt` broker plus clients run with `QT_QPA_PLATFORM=offscreen` and a stub `ffplay` on PATH (done 2026-11-09).
- Public repo: no personal hostnames, IPs or credentials. Deployment specifics belong in the private deployments repo.
