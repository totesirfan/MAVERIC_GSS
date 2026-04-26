"""End-to-end check on scripts/migrate_logs.py.

Feeds one RX record (old shape, with nested ``telemetry`` array) and one
TX record (old shape, with flat ``ax25`` / ``csp`` alongside the envelope)
through the migration script; asserts the output is shaped exactly the
same as what the live writers would emit today.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


def _load_migrate_module():
    here = Path(__file__).resolve().parent
    script = here.parent / "scripts" / "migrate_logs.py"
    spec = importlib.util.spec_from_file_location("migrate_logs", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_OLD_RX = {
    "v": "5.6.0",
    "mission": "maveric",
    "mission_name": "MAVERIC",
    "pkt": 3,
    "gs_ts": "2026-04-21 15:52:21 UTC",
    "operator": "irfan",
    "station": "GS-0",
    "frame_type": "ASM+GOLAY",
    "tx_meta": "probe",
    "raw_hex": "deadbeef",
    "payload_hex": "dead",
    "raw_len": 4,
    "payload_len": 2,
    "duplicate": False,
    "uplink_echo": True,
    "unknown": False,
    "warnings": ["noisy"],
    "telemetry": [
        {"domain": "eps", "key": "vbatt", "value": 7.1,
         "ts_ms": 1714053603500, "unit": "V", "display_only": False},
    ],
    "_rendering": {"row": {"num": {"value": 3}}, "detail_blocks": []},
    "mission_log": {"cmd": {"cmd_id": "eps_hk"}, "fragments": ["ignored"]},
}

_OLD_TX = {
    "n": 1,
    "ts": "2026-04-21T15:52:21+00:00",
    "type": "mission_cmd",
    "operator": "irfan",
    "station": "GS-0",
    "display": {"title": "com_ping", "subtitle": "EPS"},
    "mission_payload": {"cmd_id": "com_ping", "dest": "EPS",
                        "src": "GS", "echo": "NONE", "ptype": "CMD"},
    "raw_hex": "010203",
    "raw_len": 3,
    "hex": "0102030405",
    "len": 5,
    "frame_label": "ASM+Golay",
    "uplink_mode": "ASM+Golay",
    "ax25": {"src_call": "KK6ZWE", "src_ssid": 0},
    "csp": {"prio": 2, "dest": 8},
}


def test_migrate_rx_splits_telemetry_and_renames_fields():
    mig = _load_migrate_module()
    out = mig.migrate_entry(_OLD_RX, session_id="downlink_legacy", mission_id="maveric")
    out = list(out)
    rx, tel = out[0], out[1]

    assert rx["event_kind"] == "rx_packet"
    assert rx["session_id"] == "downlink_legacy"
    assert rx["seq"] == 3
    assert rx["mission_id"] == "maveric"
    assert rx["wire_hex"] == "deadbeef"
    assert rx["inner_hex"] == "dead"
    assert rx["wire_len"] == 4
    assert rx["inner_len"] == 2
    assert rx["uplink_echo"] is True
    # `mission_log` was the legacy name — now `mission`, with `fragments` dropped
    assert rx["mission"]["cmd"]["cmd_id"] == "eps_hk"
    assert "fragments" not in rx["mission"]

    assert tel["event_kind"] == "parameter"
    assert tel["rx_event_id"] == rx["event_id"]
    assert tel["name"] == "eps.vbatt"
    assert tel["value"] == 7.1
    assert tel["unit"] == "V"
    assert "domain" not in tel and "key" not in tel


def test_migrate_tx_folds_ax25_and_csp_under_mission():
    mig = _load_migrate_module()
    out = list(mig.migrate_entry(_OLD_TX, session_id="uplink_legacy", mission_id="maveric"))
    assert len(out) == 1
    tx = out[0]

    assert tx["event_kind"] == "tx_command"
    assert tx["session_id"] == "uplink_legacy"
    assert tx["seq"] == 1
    assert tx["cmd_id"] == "com_ping"
    assert tx["dest"] == "EPS"
    assert tx["uplink_mode"] == "ASM+Golay"
    assert tx["inner_hex"] == "010203"
    assert tx["inner_len"] == 3
    assert tx["wire_hex"] == "0102030405"
    assert tx["wire_len"] == 5
    assert tx["mission"]["ax25"]["src_call"] == "KK6ZWE"
    assert tx["mission"]["csp"]["dest"] == 8
    assert tx["mission"]["display"]["title"] == "com_ping"
    assert tx["mission"]["payload"]["cmd_id"] == "com_ping"


def test_migrate_file_round_trip(tmp_path):
    mig = _load_migrate_module()

    (tmp_path / "json").mkdir()
    src = tmp_path / "json" / "downlink_20260421_155221_GS-0_irfan.jsonl"
    src.write_text(json.dumps(_OLD_RX) + "\n" + json.dumps(_OLD_TX) + "\n")

    rc = mig.main([str(tmp_path), "--mission-id", "maveric"])
    assert rc == 0

    out_path = tmp_path / "json.v2" / src.name
    assert out_path.is_file()

    lines = out_path.read_text().splitlines()
    assert len(lines) == 3  # rx + parameter + tx
    kinds = [json.loads(line)["event_kind"] for line in lines]
    assert kinds == ["rx_packet", "parameter", "tx_command"]


def test_migrate_passthrough_new_shape_records():
    """Non-telemetry records that already carry event_kind pass through untouched."""
    mig = _load_migrate_module()
    new = {
        "event_id": "abc", "event_kind": "rx_packet",
        "session_id": "s", "ts_ms": 1, "ts_iso": "x",
        "seq": 1, "v": "5.7.0", "mission_id": "maveric",
        "operator": "", "station": "",
    }
    out = list(mig.migrate_entry(new, session_id="s", mission_id="maveric"))
    assert out == [new]


def test_migrate_telemetry_to_parameter():
    """event_kind="telemetry" records in the v2 unified shape get renamed to "parameter"."""
    mig = _load_migrate_module()
    src = {
        "event_id": "t1", "event_kind": "telemetry",
        "session_id": "x", "ts_ms": 1, "ts_iso": "1970-01-01T00:00:00.001+00:00",
        "seq": 1, "v": "1.0",
        "mission_id": "maveric", "operator": "", "station": "",
        "rx_event_id": "abc",
        "domain": "gnc", "key": "RATE", "value": [1, 2, 3],
        "unit": "rad/s", "display_only": False,
    }
    out = mig._migrate_telemetry_to_parameter(src)
    assert out["event_kind"] == "parameter"
    assert out["name"] == "gnc.RATE"
    assert out["value"] == [1, 2, 3]
    assert out["v"] == "1.0"          # version field unchanged
    assert out["unit"] == "rad/s"
    assert out["rx_event_id"] == "abc"
    assert "domain" not in out and "key" not in out


def test_migrate_telemetry_to_parameter_no_domain():
    """When domain is absent, name is just the key."""
    mig = _load_migrate_module()
    src = {
        "event_id": "t2", "event_kind": "telemetry",
        "session_id": "x", "ts_ms": 1, "ts_iso": "x",
        "seq": 1, "v": "1.0", "mission_id": "maveric",
        "operator": "", "station": "",
        "rx_event_id": "abc",
        "domain": "", "key": "RATE", "value": 9.8,
        "unit": "", "display_only": False,
    }
    out = mig._migrate_telemetry_to_parameter(src)
    assert out["name"] == "RATE"


def test_migrate_telemetry_passthrough_via_migrate_entry():
    """migrate_entry routes v2-shape telemetry records through the rename."""
    mig = _load_migrate_module()
    src = {
        "event_id": "t3", "event_kind": "telemetry",
        "session_id": "x", "ts_ms": 1, "ts_iso": "x",
        "seq": 1, "v": "1.0", "mission_id": "maveric",
        "operator": "", "station": "",
        "rx_event_id": "e1",
        "domain": "eps", "key": "vbatt", "value": 7.1,
        "unit": "V", "display_only": False,
    }
    out = list(mig.migrate_entry(src, session_id="x", mission_id="maveric"))
    assert len(out) == 1
    assert out[0]["event_kind"] == "parameter"
    assert out[0]["name"] == "eps.vbatt"
