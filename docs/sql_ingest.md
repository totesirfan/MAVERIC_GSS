# SQL ingest

Each session = 4 files under `logs/`:

```
json/downlink_<ts>_<station>_<op>.jsonl   # rx_packet + telemetry events
json/uplink_<ts>_<station>_<op>.jsonl     # tx_command events
text/... (human-readable, ignore for SQL)
```

Every JSONL line carries a common envelope:

```
event_id, event_kind, session_id, ts_ms, ts_iso,
seq, v, mission_id, operator, station
```

`event_kind` is one of: `rx_packet`, `tx_command`, `telemetry`.

## Split the stream by kind

```bash
jq -c 'select(.event_kind != "telemetry")' file.jsonl > events.jsonl
jq -c 'select(.event_kind == "telemetry")' file.jsonl > tel.jsonl
```

## Tables

```sql
CREATE TABLE events (
  event_id    TEXT PRIMARY KEY,
  event_kind  TEXT NOT NULL,
  session_id  TEXT NOT NULL,
  ts_ms       BIGINT NOT NULL,
  ts_iso      TIMESTAMPTZ NOT NULL,
  seq         INTEGER NOT NULL,
  v           TEXT, mission_id TEXT, operator TEXT, station TEXT,
  -- rx_packet only:
  frame_type  TEXT, transport_meta TEXT,
  wire_hex    TEXT, wire_len INTEGER,
  inner_hex   TEXT, inner_len INTEGER,
  duplicate   BOOLEAN, uplink_echo BOOLEAN, unknown BOOLEAN,
  warnings    JSONB,
  -- tx_command only:
  cmd_id      TEXT, dest TEXT, src TEXT, echo TEXT, ptype TEXT,
  frame_label TEXT, uplink_mode TEXT,
  -- mission-specific:
  mission     JSONB
);

CREATE TABLE telemetry (
  event_id    TEXT PRIMARY KEY,
  rx_event_id TEXT REFERENCES events(event_id),
  session_id  TEXT NOT NULL,
  ts_ms       BIGINT NOT NULL,
  ts_iso      TIMESTAMPTZ NOT NULL,
  seq         INTEGER NOT NULL,
  domain      TEXT NOT NULL,
  key         TEXT NOT NULL,
  value       JSONB NOT NULL,
  unit        TEXT,
  display_only BOOLEAN
);

CREATE INDEX events_ts ON events (ts_ms);
CREATE INDEX tel_dk    ON telemetry (domain, key, ts_ms);
```

## Load (Postgres)

```sql
CREATE TEMP TABLE stage (doc JSONB);
\COPY stage FROM 'events.jsonl';

INSERT INTO events SELECT
  doc->>'event_id', doc->>'event_kind', doc->>'session_id',
  (doc->>'ts_ms')::bigint, (doc->>'ts_iso')::timestamptz,
  (doc->>'seq')::int,
  doc->>'v', doc->>'mission_id', doc->>'operator', doc->>'station',
  doc->>'frame_type', doc->>'transport_meta',
  doc->>'wire_hex', (doc->>'wire_len')::int,
  doc->>'inner_hex', (doc->>'inner_len')::int,
  (doc->>'duplicate')::bool, (doc->>'uplink_echo')::bool, (doc->>'unknown')::bool,
  doc->'warnings',
  doc->>'cmd_id', doc->>'dest', doc->>'src', doc->>'echo', doc->>'ptype',
  doc->>'frame_label', doc->>'uplink_mode',
  doc->'mission'
FROM stage;
```

Telemetry loads the same way, with its own columns.

## Queries

```sql
-- vbatt over time
SELECT ts_ms, (value #>> '{}')::float
FROM telemetry WHERE domain='eps' AND key='vbatt' ORDER BY ts_ms;

-- pings sent today
SELECT ts_iso, station, dest FROM events
WHERE event_kind='tx_command' AND cmd_id='com_ping'
  AND ts_iso::date = CURRENT_DATE;

-- packet + its fragments
SELECT e.cmd_id, t.domain, t.key, t.value
FROM events e JOIN telemetry t ON t.rx_event_id = e.event_id
WHERE e.session_id = $1 ORDER BY e.seq;
```

## Notes

- Scalar telemetry values: cast with `(value #>> '{}')::float` (or `::int`).
- Structured telemetry values (bitfield dicts): read via `value->>'KEY'` / `value->'KEY'`.
- Idempotent re-ingest: `event_id` is a uuid4 hex, stable per record. `INSERT … ON CONFLICT (event_id) DO NOTHING`.
- Session is the file stem (e.g. `downlink_20260423_105655_GS-1_irfan`) — matches `session_id` in every row.
