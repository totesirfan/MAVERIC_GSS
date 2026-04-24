"""GNC command-handler dispatch: parsed cmd dict → decoded register dict.

Each handler returns `{register_name: decoded_dict}` or `None`. The
snapshot store does not care which command produced a value; last
write wins for any shared register slot.
"""

from __future__ import annotations

from typing import Callable, Iterator

from mav_gss_lib.missions.maveric.telemetry.semantics.nvg_sensors import (
    _handle_nvg_get_1,
    _handle_nvg_heartbeat,
)

from .gnc_schema import decode_register


def _handle_mtq_get_1(cmd: dict) -> dict[str, dict] | None:
    """Decode an `mtq_get_1` RES (or echo/ACK) into a one-entry dict."""
    typed = cmd.get("typed_args") or []
    extras = cmd.get("extra_args") or []

    if len(typed) < 2:
        return None

    try:
        module = int(typed[0]["value"])
        register = int(typed[1]["value"])
    except (ValueError, TypeError, KeyError):
        return None

    # typed_args[2] is the first token that fell into the "Reg Data"
    # slot from the schema; the rest of the data tokens are in extras.
    reg_data_tokens: list[str] = []
    if len(typed) > 2:
        reg_data_tokens.append(str(typed[2]["value"]))
    reg_data_tokens.extend(str(t) for t in extras)

    decoded = decode_register(module, register, reg_data_tokens)
    return {decoded.name: decoded.to_dict()}


# GNC Planner mode enum — separate from the MTQ STAT.MODE enum.
# Per MAVERIC flight software: 0=Safe, 1=Auto, 2=Manual.
GNC_PLANNER_MODE_NAMES: dict[int, str] = {
    0: "Safe",
    1: "Auto",
    2: "Manual",
}


def _handle_gnc_get_mode(cmd: dict) -> dict[str, dict] | None:
    """Decode `gnc_get_mode` RES → `GNC_MODE` snapshot."""
    typed = cmd.get("typed_args") or []
    if len(typed) < 1:
        return None
    try:
        mode = int(typed[0]["value"])
    except (ValueError, TypeError, KeyError):
        return None
    return {
        "GNC_MODE": {
            "name": "GNC_MODE",
            "module": None,
            "register": None,
            "type": "gnc_mode",
            "unit": "",
            "value": {
                "mode": mode,
                "mode_name": GNC_PLANNER_MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
            },
            "raw_tokens": [str(mode)],
            "decode_ok": True,
            "decode_error": None,
        }
    }


def _handle_gnc_get_cnts(cmd: dict) -> dict[str, dict] | None:
    """Decode `gnc_get_cnts` RES → `GNC_COUNTERS` snapshot.

    Wire fields per commands.yml: Unexpected Safe Count,
    Unexpected Detumble Count, Sunspin Count. Maps to the dashboard's
    Reboot / De-Tumble / Sunspin counters respectively — "Reboot" on
    the mockup = unexpected safe-mode entries (which are the GNC-side
    recovery events; true power-cycle reboot count lives on
    `tlm_beacon`).
    """
    typed = cmd.get("typed_args") or []
    if len(typed) < 3:
        return None
    try:
        safe     = int(typed[0]["value"])
        detumble = int(typed[1]["value"])
        sunspin  = int(typed[2]["value"])
    except (ValueError, TypeError, KeyError):
        return None
    return {
        "GNC_COUNTERS": {
            "name": "GNC_COUNTERS",
            "module": None,
            "register": None,
            "type": "gnc_counters",
            "unit": "",
            "value": {
                "reboot": safe,       # unexpected-safe count — mockup label
                "detumble": detumble,
                "sunspin": sunspin,
                "unexpected_safe": safe,  # kept under its wire name for clarity
            },
            "raw_tokens": [str(safe), str(detumble), str(sunspin)],
            "decode_ok": True,
            "decode_error": None,
        }
    }


def _walk_fast_frame(tokens: list[str]) -> "Iterator[tuple[str, str, list[str]]]":
    """Yield `(module, register, values)` tuples from an mtq_get_fast stream.

    The stream alternates `<module>,<register>` marker tokens and raw
    value tokens. Each marker starts a new register; collect subsequent
    non-marker tokens until the next marker or end of stream.
    """
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if "," not in token:
            i += 1
            continue
        try:
            module_s, reg_s = token.split(",", 1)
            module = int(module_s)
            register = int(reg_s)
        except ValueError:
            i += 1
            continue
        j = i + 1
        values: list[str] = []
        while j < len(tokens) and "," not in tokens[j]:
            values.append(tokens[j])
            j += 1
        yield module, register, values
        i = j


def _handle_mtq_get_fast(cmd: dict) -> dict[str, dict] | None:
    """Decode `mtq_get_fast` RES — 4-page fast-frame dump.

    Wire per MAVERIC flight software: Status, Page, then a sequence of
    `<module>,<register>` markers each followed by that register's
    payload values. Pages 0-2 carry 5 registers; page 3 carries 1.

    Canonical register order across pages (MTQ_FAST_FRAME_REGS):
      CONF, TIME, DATE, MTQ_USER, STAT,
      ACT_ERR, SEN_ERR, Q, RATE, LLA,
      ATT_ERROR, ATT_ERROR_RATE, SV, MAG, MTQ,
      MTQ_USER
    """
    typed = cmd.get("typed_args") or []
    extras = cmd.get("extra_args") or []

    if len(typed) < 3:
        return None

    # typed_args[0]=Status, [1]=Page, [2]=Reg Data (first marker token);
    # extras carry the rest of the stream.
    tokens: list[str] = [str(typed[2]["value"])]
    tokens.extend(str(t) for t in extras)

    out: dict[str, dict] = {}
    for module, register, values in _walk_fast_frame(tokens):
        decoded = decode_register(module, register, values)
        out[decoded.name] = decoded.to_dict()
    return out or None


# Command → handler dispatch. Each handler returns
#   {register_name: decoded_dict}  or  None.
# To have a new command feed the dashboard, add its handler here.
# The handler can write into any register-name slot — the snapshot
# store does not care which command produced the value, so if multiple
# commands expose the same logical field they simply overwrite each
# other (last write wins).
COMMAND_HANDLERS: dict[str, Callable[[dict], dict[str, dict] | None]] = {
    "mtq_get_1":     _handle_mtq_get_1,
    "mtq_get_fast":  _handle_mtq_get_fast,
    "nvg_get_1":     _handle_nvg_get_1,
    "nvg_heartbeat": _handle_nvg_heartbeat,
    "gnc_get_mode":  _handle_gnc_get_mode,
    "gnc_get_cnts":  _handle_gnc_get_cnts,
}


def decode_from_cmd(cmd: dict) -> dict[str, dict] | None:
    """Dispatch a parsed cmd dict through the command handler table.

    Called by the mission's `extractors/gnc_res.py` extractor. Returns
    `{register_name: decoded}` or `None` if no handler is registered for
    this command. The extractor projects each `decode_ok` entry into a
    TelemetryFragment targeting the `gnc` domain.
    """
    if cmd is None:
        return None
    handler = COMMAND_HANDLERS.get(cmd.get("cmd_id"))
    if handler is None:
        return None
    return handler(cmd)
