# Telemetry — Known Architectural Smells

Short, honest list of things that aren't quite right in the v2 telemetry
pipeline as it stands today. None are bugs. Each is a place where a future
change would naturally improve the code, or where a refactor was deliberately
scoped out. Keep this file current as items are fixed or new ones appear.

---

## 1. `_format_gnc_register_lines` has its own shape dispatch

**Where:** `mav_gss_lib/missions/maveric/log_format.py` (~line 200).

**What:** The text-log formatter branches on the same shape predicates
(`is_nvg_sensor`, `is_bcd_display`, `is_adcs_tmp`, `is_nvg_heartbeat`,
`is_gnc_mode`, `is_gnc_counters`) that `display_helpers._SHAPE_DISPATCH`
already dispatches on for the compact and detail-fields renderers.

**Why not fixed:** The text-log output shape (summary line + indented
subfields, with the register name as a left-gutter `<18` column) is
structurally different from both the compact string and the `list[{name,
value}]` detail-block rows. Collapsing would force lowest-common-denominator
output.

**When to fix:** If a third renderer with a similar layout is added, or if a
new decoded shape is added that'd require teaching all three functions.
Unification would look like a third callable per `_SHAPE_DISPATCH` entry:
`log_lines_fn(reg_name, value, unit) -> list[str]`.

---

## 2. `compact_value` vs `detail_fields` fallback-path asymmetry

**Where:** `display_helpers.py` — `compact_value` handles
`None / int / float / str / list` inline before the dispatch loop;
`detail_fields` handles `list` after the loop.

**What:** Same semantics, different code organization.

**Why not fixed:** Trivially refactorable into a shared `_fallback_*` helper;
nothing's forcing it right now.

---

## 3. `is_bcd_display` predicate is semantically overloaded

**Where:** `display_helpers.py` — named after its original use (GNC TIME / DATE
BCD decoders) but now matches any dict with a string `display` key. The
spacecraft `time` decoder (`to_spacecraft_time`) deliberately produces that
shape to piggyback on the predicate.

**Why not fixed:** Renaming to `is_display_dict` / `has_display_string` would
touch every caller and wouldn't change behavior. Accept the historical name as
a mild misnomer.

**Risk if ignored:** If a future decoded value also returns `{display: "..."}`
for unrelated reasons, both it and TIME/DATE would share the same rendering
path whether that's appropriate or not.

---

## 4. Catalog construction pattern differs per domain

**Where:** `mav_gss_lib/missions/maveric/telemetry/__init__.py`.

**What:**
- `gnc` catalog: derived from the `REGISTERS` dict + a hand-maintained
  `_GNC_NON_REGISTER_ENTRIES` list for handler-emitted + beacon-only keys.
- `spacecraft` catalog: one hand-maintained `_SPACECRAFT_CATALOG` list.
- `eps` domain: no catalog at all (field names + units travel on each
  fragment).

Three different patterns.

**Why not fixed:** Each domain's source-of-truth genuinely differs. GNC has a
register table as primary metadata; spacecraft has wire-only fields; EPS has
inline field-level metadata on every fragment. Forcing a unified constructor
would flatten real differences.

**When to revisit:** If a fourth domain appears and adds a fourth pattern.

---

## 5. Mixed-case key naming within domains (pre-existing)

**Where:** Across the whole telemetry vocabulary.

**What:**
- `gnc` has UPPERCASE (`STAT`, `RATE`, `MAG`, `GNC_MODE`, `ACT_ERR`,
  `GYRO_RATE_SRC`, `MAG_SRC`) AND snake_case (`mtq_heartbeat`,
  `nvg_heartbeat`).
- `spacecraft` is all snake_case (`callsign`, `time`, `ops_stage`,
  `lppm_rbt_cnt`, etc.).
- `eps` is all UPPERCASE (`V_BAT`, `I_BAT`, `T_DIE`, `VOUT1`, …).

**Why not fixed:** Inherited convention. The snake_case gnc heartbeats and
spacecraft fields mirror the FSW/wire names; the uppercase gnc registers
follow the TensorADCS register-catalog convention. Unifying would be a
breaking rename on downstream consumers and on-disk persisted state.

**When to revisit:** On the next mission onboarding, with a documented naming
rule applied to the new mission's extractors from day one.

---

## 6. `cmd_id == "tlm_beacon"` string-compared in two display paths

**Where:** `rendering.py` and `log_format.py` both check
`cmd.get("cmd_id") == "tlm_beacon"` to pick between compact and verbose GNC
rendering.

**What:** One decision (beacon vs RES) expressed in two places as a literal
string equality.

**Why not fixed:** Real but minor duplication. Two sites isn't enough
pressure to build an abstraction; three would be.

**When to revisit:** If a future mission packet wants similar
compact-for-snapshot / verbose-for-single rendering. The abstraction would
likely be a small "render hint" field on the extractor or a per-cmd_id
renderer-mode map.

---

## 7. `platform` (`web_runtime`) domain has no catalog for non-mission domains

**Where:** `TELEMETRY_MANIFEST` in any mission. The platform telemetry router
serves `/api/telemetry/{domain}/catalog` for any domain the mission registers
with a catalog callable; missions declare their own. No platform-level catalog
primitives exist.

**What:** This is fine today — every live domain is mission-owned. But if a
platform-level domain ever needed metadata (unlikely in the current
architecture — platform owns transport/state/routing, not canonical shapes),
the catalog path would need a platform-side registration too.

**Why not fixed:** Not a real problem yet. Flagged in case the platform ever
accumulates canonical keys of its own (it shouldn't).

---

## Invariants that currently hold (keep them holding)

- **Zero `from mav_gss_lib.missions` imports in `mav_gss_lib/web_runtime/`.**
  Platform never depends on mission code.
- **Zero hardcoded domain names (`"eps"`, `"gnc"`, `"spacecraft"`, `"maveric"`)
  in `mav_gss_lib/web_runtime/`.** Domains are mission-declared.
- **Catalog is the single source of truth for canonical key vocabulary** per
  domain that has one. Invariant tests (`test_maveric_beacon.py`,
  `test_telemetry_integration.py`) enforce that no extractor emits a key
  absent from the catalog.
- **One decode path per packet:** mission extractors → `TelemetryFragment` →
  `pkt.mission_data["fragments"]`. No second decoder, no parallel
  `mission_data` keys.
- **Display paths all iterate `mission_data["fragments"]`:** text log, JSONL,
  `_rendering` snapshot. Sink symmetry is mechanical, not patched.

These invariants are what let the system stay tractable. Any violation is a
bigger smell than the items above.
