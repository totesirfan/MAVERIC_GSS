"""MAVERIC alarm predicate plugins (registered via mission.alarm_plugins).

Predicate signature mirrors the calibrator contract:
    (value: Any) -> (Severity | None, str)

Author:  Irfan Annuar - USC ISI SERC
"""
from __future__ import annotations

import math
from typing import Any

from mav_gss_lib.platform.alarms.contract import Severity


def q_norm(value: Any):
    """Quaternion-norm sanity: ‖q‖ should be 1; alarm if it drifts."""
    try:
        n = math.sqrt(sum(float(c) ** 2 for c in value))
    except (TypeError, ValueError):
        return None, ""
    err = abs(n - 1.0)
    if err > 0.10:
        return Severity.CRITICAL, f"‖q‖={n:.4f}"
    if err > 0.05:
        return Severity.WARNING, f"‖q‖={n:.4f}"
    return None, ""


def sv_eclipse_aware(value: Any):
    """Sun-vector sanity:
       - ‖SV‖ ≈ 1 when sun visible (nominal)
       - null vector (0,0,0) when in eclipse (nominal)
       - anything else (partial / saturated) → warning or critical
    """
    try:
        n = math.sqrt(sum(float(c) ** 2 for c in value))
    except (TypeError, ValueError):
        return None, ""
    if n < 1e-3:
        return None, "eclipse"
    if abs(n - 1.0) < 0.05:
        return None, ""
    if abs(n - 1.0) < 0.20:
        return Severity.WARNING, f"‖SV‖={n:.3f}"
    return Severity.CRITICAL, f"‖SV‖={n:.3f}"


PLUGINS = {
    "maveric.alarm.q_norm": q_norm,
    "maveric.alarm.sv_eclipse_aware": sv_eclipse_aware,
}
