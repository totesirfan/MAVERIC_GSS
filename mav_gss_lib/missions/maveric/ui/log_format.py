"""MAVERIC logging format helpers — declarative shape.

Builds the JSONL `mission` sub-block plus the multi-line text-log entry
for one received packet. Reads MaverMissionPayload attributes +
envelope.telemetry directly.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mav_gss_lib.missions.maveric.ui.formatters import (
    display_kind,
    render_value,
)
from mav_gss_lib.missions.maveric.ui.rendering import _ts_result

if TYPE_CHECKING:
    from mav_gss_lib.missions.maveric.packets import MaverMissionPayload
    from mav_gss_lib.platform import PacketEnvelope
    from mav_gss_lib.platform.spec import Mission


_LABEL_WIDTH = 10


def build_log_mission_data(
    payload: "MaverMissionPayload",
    envelope: "PacketEnvelope",
    mission: "Mission",
) -> dict[str, Any]:
    """Return the mission sub-block of the rx_packet JSONL envelope.

    Telemetry fragments are NOT included here — the platform emits each
    one as its own `event_kind="telemetry"` record, back-pointing to the
    parent packet via `rx_event_id`. CRC-related fields are emitted as
    structured booleans/ints so SQL ingest doesn't have to strip prefixes.
    """
    h = payload.header or {}
    out: dict[str, Any] = {
        "header":          dict(h),
        "valid_crc":       payload.valid_crc,
        "csp_header":      dict(payload.csp_header) if payload.csp_header else None,
        "csp_plausible":   payload.csp_plausible,
        "csp_crc32":       payload.csp_crc32,
        "csp_crc32_valid": payload.csp_crc32_valid,
        "stripped_hdr":    payload.stripped_hdr,
        "args_hex":        payload.args_raw.hex(),
    }
    if envelope.transport_meta:
        out["transport_meta"] = dict(envelope.transport_meta)
    return out


def format_log_lines(
    payload: "MaverMissionPayload",
    envelope: "PacketEnvelope",
    mission: "Mission",
) -> list[str]:
    """Multi-line text-log entry for one packet.

    Output sections (each a single line, two-space indent + label-aligned):
      MODE      — envelope.frame_type
      AX25      — decoded AX.25 header (when stripped_hdr present)
      ROUTING   — Src:<src>  Dest:<dest>  Echo:<echo>
      CMD       — id:<cmd_id>  type:<ptype>
      TS        — formatted ts_result if any (else GS receive time)
      CSP       — payload.csp_header fields (skip if csp_header is None)
      INTEGRITY — Body CRC: ok|fail   CSP CRC32: ok|fail|n/a
      SIZE      — wire <len(envelope.raw)>B  inner <len(envelope.payload)>B
                  args <len(payload.args_raw)>B
      TLM       — one indented line per fragment, formatted via render_value
    """
    h = payload.header or {}
    lines: list[str] = []

    lines.append(_field_line("MODE", envelope.frame_type))

    # AX.25 header
    if payload.stripped_hdr:
        try:
            from mav_gss_lib.platform.framing.ax25 import ax25_decode_header
            decoded = ax25_decode_header(bytes.fromhex(payload.stripped_hdr.replace(" ", "")))
            lines.append(_field_line(
                "AX25",
                f"Dest:{decoded['dest']['callsign']}-{decoded['dest']['ssid']}  "
                f"Src:{decoded['src']['callsign']}-{decoded['src']['ssid']}  "
                f"Ctrl:{decoded['control_hex']}  PID:{decoded['pid_hex']}",
            ))
        except Exception:
            lines.append(_field_line("AX25", payload.stripped_hdr))

    if h:
        lines.append(_field_line(
            "ROUTING",
            f"Src:{h.get('src', '?')}  Dest:{h.get('dest', '?')}  Echo:{h.get('echo', '?')}",
        ))
        lines.append(_field_line(
            "CMD",
            f"id:{h.get('cmd_id', '?')}  type:{h.get('ptype', '?')}",
        ))

    # Satellite time
    ts = _ts_result(envelope)
    if ts is not None:
        dt_utc, dt_local, raw_ms = ts
        lines.append(_field_line(
            "TS",
            f"{dt_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}  "
            f"{dt_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  ({raw_ms})",
        ))

    # CSP header
    if payload.csp_header:
        csp = payload.csp_header
        tag = "CSP V1" if payload.csp_plausible else "CSP V1 [?]"
        lines.append(_field_line(
            tag,
            f"Prio:{csp.get('prio', '?')}  Src:{csp.get('src', '?')}  "
            f"Dest:{csp.get('dest', '?')}  DPort:{csp.get('dport', '?')}  "
            f"SPort:{csp.get('sport', '?')}  Flags:0x{csp.get('flags', 0):02X}",
        ))

    # Integrity summary
    body = "ok" if payload.valid_crc else "fail"
    if payload.csp_crc32_valid is True:
        csp32 = "ok"
    elif payload.csp_crc32_valid is False:
        csp32 = "fail"
    else:
        csp32 = "n/a"
    lines.append(_field_line("INTEGRITY", f"Body CRC: {body}   CSP CRC32: {csp32}"))

    # Sizes
    lines.append(_field_line(
        "SIZE",
        f"wire {len(envelope.raw)}B  inner {len(envelope.payload)}B  "
        f"args {len(payload.args_raw)}B",
    ))

    # Telemetry — one indented line per fragment.
    for f in envelope.telemetry:
        dispatch = display_kind(mission, f.key)
        rendered = render_value(f.value, dispatch, f.unit)
        suffix = "  # raw" if f.display_only else ""
        lines.append(f"  TLM        {f.domain}.{f.key} = {rendered}{suffix}")

    return lines


def _field_line(label: str, value: str) -> str:
    return f"  {label:<{_LABEL_WIDTH}} {value}"
