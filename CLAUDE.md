# Claude-Horn

Release tier: small (`v1.0`, `v1.1`, ...).

- Server: `server/horn_server.py` (stdlib HTTP + paho-mqtt). Client: `client/claude_horn_client/__main__.py` (PySide6 tray).
- Topic and API contract: README. Change both sides together.
- Horn names live in `HORNS`/`CHAOS` in the server and as files in `sounds/`. Keep them in sync.
- Test without a GUI: a local `amqtt` broker plus clients run with `QT_QPA_PLATFORM=offscreen` and a stub `ffplay` on PATH (done 2026-11-09).
- Public repo: no personal hostnames, IPs or credentials. Deployment specifics belong in the private deployments repo.
