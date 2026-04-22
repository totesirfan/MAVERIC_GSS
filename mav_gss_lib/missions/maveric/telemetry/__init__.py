"""MAVERIC mission telemetry package root.

Semantic decoders live under `semantics/`; extractors under `extractors/`.
Task 11 adds `TELEMETRY_MANIFEST` here — the declarative per-domain
registration payload the platform `TelemetryRouter` reads at startup.

No decoder dispatch shim lives here after v2: `rx_ops.parse_packet` no
longer pre-populates `mission_data["telemetry"]` or `["gnc_registers"]`.
Extractors call the semantic decoders directly and the resulting
TelemetryFragments are the single per-packet decoded payload.
"""

from __future__ import annotations
