"""MAVERIC routing rule. Given (cmd_id, dest), derive the expected VerifierSet.

Rule table (spec §5.1):
  LPPM → uppm_ack + lppm_ack + res_from_lppm + nack_uppm + nack_lppm
  UPPM → uppm_ack + res_from_uppm + nack_uppm
  HLNV → uppm_ack + hlnv_ack + res_from_hlnv + nack_uppm
  ASTR → uppm_ack + astr_ack + res_from_astr + nack_uppm
  EPS  → uppm_ack + res_from_eps + nack_uppm + nack_eps (EPS never acks)
  FTDI → empty (verification disabled)

Overrides from commands.yml (3 commands only — eps_hk, eps_cut, eps_burn):
  complete: {kind: comparison_list, ...}  → replace res_from_eps with tlm_eps_hk
  complete: none                          → remove res_from_eps

CheckWindow bounds derived from archive p95 latency with 1.5-2x headroom.
"""
from __future__ import annotations

from typing import Any

from mav_gss_lib.platform.tx.verifiers import (
    CheckWindow, VerifierSpec, VerifierSet,
)


# ─── CheckWindow bounds ───────────────────────────────────────────────

_UPPM_ACK_WIN   = CheckWindow(start_ms=0, stop_ms=10_000)
_DEST_ACK_WIN   = CheckWindow(start_ms=0, stop_ms=15_000)
_RES_WIN        = CheckWindow(start_ms=0, stop_ms=30_000)
_NACK_WIN       = CheckWindow(start_ms=0, stop_ms=30_000)
_TLM_WIN        = CheckWindow(start_ms=0, stop_ms=30_000)


# ─── Helpers ──────────────────────────────────────────────────────────

def _ack(verifier_id: str, label: str, window: CheckWindow) -> VerifierSpec:
    return VerifierSpec(
        verifier_id=verifier_id, stage="received",
        check_window=window, display_label=label, display_tone="info",
    )


def _res(dest_lower: str) -> VerifierSpec:
    return VerifierSpec(
        verifier_id=f"res_from_{dest_lower}", stage="complete",
        check_window=_RES_WIN, display_label="RES", display_tone="success",
    )


def _nack(suffix: str) -> VerifierSpec:
    return VerifierSpec(
        verifier_id=f"nack_{suffix}", stage="failed",
        check_window=_NACK_WIN, display_label="NACK", display_tone="danger",
    )


# ─── Routing rule ─────────────────────────────────────────────────────

def derive_verifier_set(*, cmd_id: str, dest: str) -> VerifierSet:
    """Pure derivation. cmd_id is accepted for future per-cmd tuning
    (not used in the base table today)."""
    _ = cmd_id  # currently unused; signature future-proofed
    d = dest.upper()

    if d == "LPPM":
        return VerifierSet(verifiers=(
            _ack("uppm_ack", "UPPM", _UPPM_ACK_WIN),
            _ack("lppm_ack", "LPPM", _DEST_ACK_WIN),
            _res("lppm"),
            _nack("uppm"),
            _nack("lppm"),
        ))
    if d == "UPPM":
        return VerifierSet(verifiers=(
            _ack("uppm_ack", "UPPM", _UPPM_ACK_WIN),
            _res("uppm"),
            _nack("uppm"),
        ))
    if d == "HLNV":
        return VerifierSet(verifiers=(
            _ack("uppm_ack", "UPPM", _UPPM_ACK_WIN),
            _ack("hlnv_ack", "HLNV", _DEST_ACK_WIN),
            _res("hlnv"),
            _nack("uppm"),
        ))
    if d == "ASTR":
        return VerifierSet(verifiers=(
            _ack("uppm_ack", "UPPM", _UPPM_ACK_WIN),
            _ack("astr_ack", "ASTR", _DEST_ACK_WIN),
            _res("astr"),
            _nack("uppm"),
        ))
    if d == "EPS":
        return VerifierSet(verifiers=(
            _ack("uppm_ack", "UPPM", _UPPM_ACK_WIN),
            _res("eps"),
            _nack("uppm"),
            _nack("eps"),
        ))
    # FTDI + any unknown → empty (verification disabled).
    return VerifierSet(verifiers=())


# ─── Override application ─────────────────────────────────────────────

def apply_override(base: VerifierSet, *, override: dict[str, Any]) -> VerifierSet:
    """Apply a per-command override block to a routing-rule-derived VerifierSet.

    Supported override shapes:
      - {"complete": "none"}  → drop any CompleteVerifier
      - {"complete": {"kind": "comparison_list", "parameter": {"domain": D, "key": K},
                      "comparison": "value_change", "check_window": {"stop_ms": N}}}
           → replace any CompleteVerifier with a single tlm_<domain>_<key> spec

    Other fields inherit from the base VerifierSet.
    """
    verifiers = list(base.verifiers)

    # Accept `complete: none` (string) and `complete: null` / `~` (Python None,
    # from PyYAML). An absent key (no `complete:` at all) is handled differently
    # below — routing-rule default stays.
    if "complete" in override:
        complete_override = override["complete"]
        # Drop existing complete verifiers.
        verifiers = [v for v in verifiers if v.stage != "complete"]
        if complete_override in ("none", None):
            pass  # no replacement — terminal via UPPM ack only
        elif isinstance(complete_override, dict) and complete_override.get("kind") == "comparison_list":
            param = complete_override["parameter"]
            domain = param["domain"]
            key = param["key"]
            stop_ms = complete_override.get("check_window", {}).get("stop_ms", _TLM_WIN.stop_ms)
            verifiers.append(VerifierSpec(
                verifier_id=f"tlm_{domain}_{key}",
                stage="complete",
                check_window=CheckWindow(start_ms=0, stop_ms=stop_ms),
                display_label="TLM", display_tone="success",
            ))

    return VerifierSet(verifiers=tuple(verifiers))
