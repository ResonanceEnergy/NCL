# NCL — iPhone Data Contract / Event Schema v1

**Filename:** `docs/ncl_iphone_data_contract_v1.md`  
**Version:** 1.0 (draft) — schema namespace: `ncl.iphone.v1`  
**Goal:** Define a clear, privacy-first contract for every iPhone-originating event NCL will ingest: required permissions, ingestion method, default retention tier, privacy classification, and derived features.

---

## Summary
- Local-first, metadata-first contract covering core iPhone streams (Health, Screen Time, Notifications, Focus, Shortcuts, Location-state, Connectivity, etc.).
- No raw-content retention by default; prefer metadata and derived signals.  
- Supports two ingestion patterns: **zero-app** (Shortcuts + exports) and **companion-app** (HealthKit + system APIs). Default recommendation for v1: **zero-app (Shortcuts/Exports)** unless you explicitly want a companion app.

---

## Design principles ✅
- **Local-first & reversible exportable** — user can export and delete all data.  
- **Metadata-first / No raw content** — raw audio, images, or message contents are disallowed unless explicitly consented and justified.  
- **Least-privilege ingestion** — prefer Shortcuts/exports; companion app only if necessary.  
- **Schema & versioning** — strict versioned JSON Schema, backward-compatible migrations.

---

## Common event envelope (required fields)
All iPhone-origin events MUST use this envelope.

```json
{
  "event_id": "uuidv4",
  "event_type": "ncl.<stream>.<action>",
  "schema_version": "ncl.iphone.v1",
  "timestamp": "ISO-8601 UTC",
  "ingestion_method": "shortcut|manual_export|companion_app|healthkit",
  "permission": { "granted": true, "scope": "read:health|export:screen_time", "granted_at": "..." },
  "retention_tier": "ephemeral|short|medium|long",
  "privacy_level": "metadata_only|derived|sensitive",
  "provenance": { "source": "HealthKit|Shortcut|Export", "device_hash": "sha256:..." },
  "payload": { /* stream-specific content */ }
}
```

> Note: `privacy_level` maps to the doctrine labels used in insights: `metadata_only (U)`, `derived (D)`, `sensitive (C)`.

---

## Retention tiers (defaults)
- **ephemeral** — raw/temporary data kept < 24 hours (default for raw audio blobs, deleted immediately).  
- **short** — 30 days (notification metadata, pickups, session-level telemetry).  
- **medium** — 1 year (aggregates and derived features for trending).  
- **long** — user-managed / archived (exportable, encrypted; used only with explicit opt-in).

Retention must be user-configurable per-tier with an audit log for deletions.

---

## Ingestion methods & permission modalities
- **Shortcuts Automation (recommended for v1 zero-app):** user installs the Shortcuts automation pack; emits structured JSON events to Files/Local DB/Clipboard. No private entitlements required. Suitable for: pickups, NFC rituals, Focus toggles, Shortcuts events, notification snapshot via user export.
- **Manual exports:** Health export, Screen Time CSV/JSON — ingested by user drag/drop or File import. Suitable for historical backfill.
- **Companion app (optional):** uses HealthKit, Background Fetch, Notification Service Extension — required only if you need continuous, higher-fidelity ingestion. Use least-privilege entitlements.

---

## Privacy classification (quick reference)
- `metadata_only` (U): No content, only counts/hashes/timestamps (default for notifications, calls, connectivity).  
- `derived` (D): Aggregated/derived signals (attention fragmentation, reaction score).  
- `sensitive` (C): Raw content or personally identifying health content — disallowed by default; requires explicit consent and stronger retention controls.

---

## Stream-by-stream contract (selected highlights)
Each entry lists: Source/API • Permissions • Ingestion method(s) • Default retention • Privacy level • Derived features • Example payload.

1) Screen Time session
- Source: Screen Time exports / iOS system snapshot
- Permissions: user Screen Time export (manual) or Shortcuts snapshot
- Ingestion: `manual_export` | `shortcut`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: session_count, session_durations, attention_fragmentation, top_app
- Payload example:
```json
{"event_type":"ncl.screentime.session","payload":{"start":"2026-02-19T08:00:00Z","end":"2026-02-19T08:45:00Z","duration_s":2700,"top_app_hash":"sha256:..."}}
```

2) Pickups (unlock events)
- Source: Shortcuts / Focus + ScreenTime inference
- Permissions: user-approved Shortcut
- Ingestion: `shortcut`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: pickups_per_hour, micro-pauses, compulsion_index

3) Notifications (metadata only)
- Source: Notification export via Shortcut or companion app
- Permissions: user Shortcut permission OR notification access in-app
- Ingestion: `shortcut` | `companion_app`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: notifications_per_app, burst_events, reaction_latency
- Payload keys: `app_hash`, `category`, `delivered_at`, `is_actionable`

4) Health vitals (HR, HRV, SpO2, Respiratory Rate, Sleep)
- Source: HealthKit export / Shortcuts health snapshot
- Permissions: HealthKit read permissions (explicit per-type)
- Ingestion: `healthkit` | `manual_export` | `shortcut` (where available)
- Retention: `medium` (default) — raw readings `short`, aggregated trends `medium`
- Privacy: `sensitive` for raw readings; derived outputs default to `derived` (D)
- Derived: recovery_debt, energy_forecast, illness_onset_detector
- Payload example (heart rate):
```json
{"event_type":"ncl.health.heart_rate","payload":{"value":58,"unit":"bpm","recorded_at":"2026-02-19T06:30:00Z","device":"apple_watch"}}
```

5) Focus Mode & Focus Filters
- Source: Focus API / Shortcuts
- Permissions: user system permission (Focus state readable)
- Ingestion: `shortcut` | `companion_app`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: role_shift_events, focus_adherence

6) Calendar / Reminders
- Source: Calendar export / Shortcuts
- Permissions: Calendar/Reminders read
- Ingestion: `shortcut` | `manual_export`
- Retention: `short|medium` depending on event sensitivity
- Privacy: `metadata_only`
- Derived: schedule_density, time_to_first_work, decision_debt

7) Calls / Telephony metadata
- Source: Call history export
- Permissions: user-provided export
- Ingestion: `manual_export` | `companion_app` (metadata only)
- Retention: `short`
- Privacy: `metadata_only`
- Derived: inbound_outbound_ratio, call_duration_histogram

8) Connectivity & Place fingerprints (Wi‑Fi SSID hashed, BLE counts)
- Source: Shortcuts snapshot / system export
- Permissions: none beyond Shortcut; do NOT store raw SSID or MAC
- Ingestion: `shortcut`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: place_fingerprint_hash, social_density_estimate

9) NFC tag rituals / Shortcuts events
- Source: Shortcuts (NFC trigger)
- Permissions: user Shortcut installation
- Ingestion: `shortcut`
- Retention: `short`
- Privacy: `metadata_only`
- Derived: ritual_frequency, context_marker

10) Microphone presence / Noise band / Speech presence (labels only)
- Source: local short-lived audio analysis (on-device only)
- Permissions: microphone permission + explicit consent for sensing
- Ingestion: `shortcut` | `companion_app` (on-device inference only)
- Retention: `ephemeral` for raw audio (delete immediately); store only `metadata_only` labels
- Privacy: `metadata_only`
- Derived: silence_blocks, interruption_bursts

> The remaining streams from the 150-insight list follow this same envelope; see `src/insights_150.json` for mapping to derived features.

---

## JSON Schema examples (minimal)
- Full machine-readable JSON Schema artifacts should be generated from this draft as the next step.

Envelope (abbreviated JSON Schema):
```json
{ "$id":"ncl.iphone.v1.event", "type":"object", "required":["event_id","event_type","timestamp","schema_version","privacy_level"], "properties":{"event_id":{"type":"string"},"event_type":{"type":"string"},"timestamp":{"type":"string","format":"date-time"},"privacy_level":{"type":"string"}}}
```

---

## Consent, audit & governance
- Every permission grant/deny must be emitted as `ncl.consent.change` (auditable).  
- Store an append-only local audit log of consent changes + retention/deletion events.  
- RBAC: Mission Control & agent runtimes must check `permission.granted` before requesting a dataset.

---

## Schema versioning & migration
- Schema namespace: `ncl.iphone.v1`  
- Backward compatibility guarantee for patch (<major.minor.patch>): only non-breaking changes for minor/patch.  
- Migration policy: include `deprecated_fields` with a sunset date in migration metadata.

---

## Operational notes / implementer checklist 🔧
1. Produce machine-readable JSON Schemas for envelope + top 20 streams.  
2. Build Shortcuts Automation Pack v1 (emit envelope-compliant JSON files to Files folder).  
3. Implement local DB schema + retention enforcement.  
4. Add export/erase UI + audit log viewer.  
5. If companion app: scaffold HealthKit permissions & Notification metadata extension.

---

## Next steps (suggested) — progress
- [x] Review & approve Data Contract v1.
- [x] Generate machine-readable JSON Schema files — added at `schemas/ncl.iphone.v1/`.
- [x] Build Shortcuts Automation Pack v1 — scaffolded at `shortcuts_pack/v1/` (includes templates + emulator).
- [x] Prototype companion app (skeleton) — scaffolded at `ios/CompanionApp/`.
- [ ] Finalize & publish quick-start Shortcuts bundle (follow-up).

---

### Quick decision for you
- Recommended initial shipping mode for Data Contract v1: **zero custom iOS app** (Shortcuts + exports).  
- Reply `companion` if you want this contract tailored to a minimal companion app instead.

---

For the full machine-readable schema and Shortcuts pack I can generate next — which task should I do now? (generate JSON Schema files, scaffold Shortcuts pack, or prototype companion app skeleton)
