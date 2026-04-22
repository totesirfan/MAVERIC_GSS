"""TelemetryField — shared type for mission telemetry decoder outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelemetryField:
    """One decoded telemetry field.

    `value` is the engineering value (scaled). `raw` is the pre-scaling
    integer, kept for debug/tests. `raw` is intentionally omitted from
    to_dict() — the JSONL log already carries raw bytes in payload_hex.
    """
    name: str
    value: float | int
    unit: str
    raw: int | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "unit": self.unit}
