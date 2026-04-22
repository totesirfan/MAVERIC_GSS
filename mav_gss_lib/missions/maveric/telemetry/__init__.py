"""MAVERIC mission telemetry package root.

Semantic decoders live under `semantics/`; extractors under `extractors/`.
This file exports `TELEMETRY_MANIFEST` — the declarative per-domain
registration payload the platform `TelemetryRouter` reads at startup.

No decoder dispatch shim lives here after v2: `rx_ops.parse_packet` no
longer pre-populates `mission_data["telemetry"]` or `["gnc_registers"]`.
Extractors call the semantic decoders directly and the resulting
TelemetryFragments are the single per-packet decoded payload.
"""

from __future__ import annotations

# Relocated schema path — Task 7a moved the register catalog out of the
# legacy gnc_registers/ package. Do NOT re-introduce a
# `from ...telemetry.gnc_registers` import here; that package is deleted
# in Task 16.
from mav_gss_lib.missions.maveric.telemetry.semantics.gnc_schema import REGISTERS


# Canonical `gnc` keys that do NOT correspond to addressable spacecraft
# registers — RES handler output (GNC_MODE, GNC_COUNTERS) and beacon
# shared-prefix / tail fields (GYRO_RATE_SRC, MAG_SRC, heartbeats).
# module and register are null because they have no (module, register)
# address on the wire.
#
# Listed here so the catalog is the single source of truth for "what
# canonical gnc keys exist + their metadata", matching the platform
# contract where consumers discover keys through
# `useTelemetryCatalog('gnc')` rather than through extractor source.
_GNC_NON_REGISTER_ENTRIES = [
    {"module": None, "register": None, "name": "GNC_MODE",
     "type": "gnc_mode", "unit": "",
     "notes": "Planner mode (Safe/Auto/Manual) from gnc_get_mode RES or tlm_beacon."},
    {"module": None, "register": None, "name": "GNC_COUNTERS",
     "type": "gnc_counters", "unit": "",
     "notes": "Reboot / De-Tumble / Sunspin counters from gnc_get_cnts RES or tlm_beacon."},
    {"module": None, "register": None, "name": "GYRO_RATE_SRC",
     "type": "uint8", "unit": "",
     "notes": "Active gyro-rate source selector, from tlm_beacon. Raw int."},
    {"module": None, "register": None, "name": "MAG_SRC",
     "type": "uint8", "unit": "",
     "notes": "Active magnetometer source selector, from tlm_beacon. Raw int."},
    {"module": None, "register": None, "name": "mtq_heartbeat",
     "type": "uint8", "unit": "",
     "notes": "MTQ subsystem heartbeat byte from tlm_beacon shared prefix."},
    {"module": None, "register": None, "name": "nvg_heartbeat",
     "type": "uint8", "unit": "",
     "notes": "NVG subsystem heartbeat byte from tlm_beacon shared prefix."},
]


def _gnc_catalog():
    """Serve the GNC register catalog at /api/telemetry/gnc/catalog.

    The platform does not interpret the shape — it passes the body
    through verbatim. The frontend's GncProvider consumes it as
    `CatalogEntry[]` keyed by register name.

    Includes both addressable spacecraft registers (from REGISTERS)
    and non-register canonical keys (handler-emitted + beacon-only).
    Non-register entries carry `module: null, register: null` so
    consumers that care about the distinction (e.g. the Registers
    table) can filter by `module !== null`.
    """
    register_entries = [
        {"module": m, "register": r,
         "name": REGISTERS[(m, r)].name,
         "type": REGISTERS[(m, r)].type,
         "unit": REGISTERS[(m, r)].unit,
         "notes": REGISTERS[(m, r)].notes}
        for (m, r) in sorted(REGISTERS.keys())
    ]
    return register_entries + list(_GNC_NON_REGISTER_ENTRIES)


TELEMETRY_MANIFEST: dict[str, dict] = {
    # eps_hk 48 engineering fields. Default LWW merge; no catalog
    # (field names travel on each fragment's `unit` already).
    "eps":      {},
    # GNC register catalog served via the platform route; live values
    # come in through the extractor + router.
    "gnc":      {"catalog": _gnc_catalog},
    # Spacecraft-wide state carried in tlm_beacon's shared prefix
    # (platform time, ops_stage, reboot counters, hn/ab state, ertc
    # heartbeat). Populated on every beacon packet regardless of
    # beacon_type. No catalog — field names are self-explanatory and
    # enumerated in extractors/tlm_beacon.py's COMMON_MAPPINGS table.
    "spacecraft": {},
    # Future-domain examples showing every extension point:
    #   "thermal": {
    #       "merge": sequence_monotonic("seq"),         # custom merge
    #       "load_entries": drop_entries_without_seq,   # paired loader
    #       "catalog": _thermal_catalog,
    #   }
}

__all__ = ["TELEMETRY_MANIFEST"]
