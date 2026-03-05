
# iPhone Shortcut Recipe (Local‑Only)

Goal: Send an NCL event to your MacBook over local network.

## Pre-req
- Mac relay running: `python3 runtime/relay_server.py --host 0.0.0.0 --port 8787`
- Your iPhone and Mac are on the same LAN/Wi‑Fi.

## Shortcut steps
1) **Text** (or Dictionary) → build a JSON payload. Minimum fields:

```json
{
  "schema_version": "ncl.event.v1",
  "event_id": "ulid-or-uuid",
  "event_type": "device.focus.changed",
  "occurred_at": "2026-02-18T20:25:00-07:00",
  "source": {"device":"iphone","origin":"shortcuts","collector_version":"shortcuts-pack.v1"},
  "privacy": {"level":"P1","raw_retention":"none","derived_retention_days":365},
  "payload": {"from":"Personal","to":"Work"}
}
```

2) **Get Contents of URL**
- URL: `http://<MAC_LAN_IP>:8787/event`
- Method: POST
- Body: JSON
- Headers: `Content-Type: application/json`

3) Optional: If you want offline fallback, also **Append to File** on iPhone in `On My iPhone/NCL/outbox.ndjson`.

## Notes
- Keep payloads metadata-first.
- Do not send P2/P3 unless you explicitly mean to.

