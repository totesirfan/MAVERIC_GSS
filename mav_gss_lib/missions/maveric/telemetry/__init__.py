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


def _gnc_catalog():
    """Serve the GNC register catalog at /api/telemetry/gnc/catalog.

    The platform does not interpret the shape — it passes the body
    through verbatim. The frontend's GncProvider consumes it as
    `CatalogEntry[]` keyed by register name.
    """
    return [
        {"module": m, "register": r,
         "name": REGISTERS[(m, r)].name,
         "type": REGISTERS[(m, r)].type,
         "unit": REGISTERS[(m, r)].unit,
         "notes": REGISTERS[(m, r)].notes}
        for (m, r) in sorted(REGISTERS.keys())
    ]


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
    "platform": {},
    # Future-domain examples showing every extension point:
    #   "thermal": {
    #       "merge": sequence_monotonic("seq"),         # custom merge
    #       "load_entries": drop_entries_without_seq,   # paired loader
    #       "catalog": _thermal_catalog,
    #   }
}

__all__ = ["TELEMETRY_MANIFEST"]
