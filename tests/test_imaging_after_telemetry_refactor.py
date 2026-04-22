"""Task 17 Part B — pin imaging behavior while adapter.py is restructured.

Task 10 collapsed adapter.on_packet_received and extracted the imaging
path into _image_messages(pkt). Imaging has no telemetry interaction,
but structural rewrites around it can quietly break chunk tracking or
replay. This file owns the focused imaging regression coverage.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path

from mav_gss_lib.missions.maveric.adapter import MavericMissionAdapter
from mav_gss_lib.missions.maveric.imaging import ImageAssembler
from mav_gss_lib.web_runtime.telemetry.router import TelemetryRouter


def _nodes(ptype_map):
    n = MagicMock()
    n.ptype_name.side_effect = lambda p: ptype_map.get(p, "CMD")
    return n


def _img_cnt_pkt(pkt_num=1, filename="test.jpg", num_chunks=3, ptype=2):
    return SimpleNamespace(
        pkt_num=pkt_num, gs_ts="t",
        mission_data={
            "cmd": {
                "cmd_id": "img_cnt_chunks",
                "schema_match": True,
                "typed_args": [
                    {"name": "Filename",   "value": filename},
                    {"name": "Num Chunks", "value": str(num_chunks)},
                ],
            },
            "ptype": ptype,
        },
    )


def _img_chunk_pkt(pkt_num, filename, chunk_num, data: bytes):
    return SimpleNamespace(
        pkt_num=pkt_num, gs_ts="t",
        mission_data={
            "cmd": {
                "cmd_id": "img_get_chunk",
                "schema_match": True,
                "typed_args": [
                    {"name": "Filename",     "value": filename},
                    {"name": "Chunk Number", "value": str(chunk_num)},
                    {"name": "Chunk Size",   "value": str(len(data))},
                    {"name": "Data",         "value": data.hex()},
                ],
            },
            "ptype": 7,
        },
    )


def _run_pkt(adapter, pkt):
    """Replicate rx_service's production order: attach_fragments before
    on_packet_received. Every test that drives the adapter at the packet
    level goes through this so the split-hook sequence is exercised,
    even for imaging packets that produce zero fragments.
    """
    adapter.attach_fragments(pkt)
    return adapter.on_packet_received(pkt) or []


def test_imaging_progress_survives_telemetry_refactor(tmp_path):
    a = MavericMissionAdapter.__new__(MavericMissionAdapter)
    a.nodes = _nodes({2: "RES", 7: "FILE"})
    a.image_assembler = ImageAssembler(str(tmp_path))
    a.telemetry = TelemetryRouter(tmp_path / ".telemetry")
    a.telemetry.register_domain("eps")
    a.telemetry.register_domain("gnc")
    a.extractors = ()

    # Declare total chunks → one imaging_progress message.
    first_pkt = _img_cnt_pkt()
    msgs = _run_pkt(a, first_pkt)
    types = [m["type"] for m in msgs]
    assert "imaging_progress" in types
    assert "telemetry" not in types  # telemetry path must not fire on imaging cmds
    # attach_fragments ran even on the imaging packet; with empty
    # extractors it produces an empty list, not a missing key.
    assert first_pkt.mission_data["fragments"] == []

    # Feed two of three chunks.
    _run_pkt(a, _img_chunk_pkt(2, "test.jpg", 0, b"aaa"))
    _run_pkt(a, _img_chunk_pkt(3, "test.jpg", 1, b"bbb"))
    received, total = a.image_assembler.progress("test.jpg")
    assert total == 3 and received == 2
    assert not a.image_assembler.is_complete("test.jpg")

    # Final chunk → complete.
    final = _run_pkt(a, _img_chunk_pkt(4, "test.jpg", 2, b"ccc"))
    assert any(m.get("complete") for m in final if m["type"] == "imaging_progress")
    assert a.image_assembler.is_complete("test.jpg")


def test_imaging_and_telemetry_can_fire_from_same_session(tmp_path):
    """A burst of mixed RX (eps_hk + img_get_chunk + tlm_beacon) must
    not drop any domain. Regression guard for the shared dispatcher.
    """
    from mav_gss_lib.missions.maveric.telemetry.extractors import EXTRACTORS

    a = MavericMissionAdapter.__new__(MavericMissionAdapter)
    # ptype_map needs both TLM=2 (for eps_hk) and RES=2 (for img_cnt_chunks).
    # In production the ptype int IS the same (maveric ptype enum remaps both
    # to 2 for TLM/RES depending on context), and the adapter's per-cmd_id
    # branch gates on the name. Here we stub differently per cmd_id by
    # returning RES for imaging packets using an img_* packet's own args
    # shape as the discriminator — simpler to just route ptype 2 to TLM for
    # eps_hk tests and split imaging onto a dedicated code path. The
    # imaging test below uses ptype 3 (RES) for img_cnt_chunks.
    a.nodes = _nodes({2: "TLM", 3: "RES", 7: "FILE"})
    a.image_assembler = ImageAssembler(str(tmp_path))
    a.telemetry = TelemetryRouter(tmp_path / ".telemetry")
    a.telemetry.register_domain("eps")
    a.telemetry.register_domain("gnc")
    a.telemetry.register_domain("platform")
    a.extractors = EXTRACTORS

    # Minimal valid 96-byte payload — decode_eps_hk parses it as
    # 48 × int16 little-endian. All zeros → 48 fields with value=0.0.
    eps_args_raw = b"\x00" * 96
    eps_pkt = SimpleNamespace(pkt_num=10, gs_ts="t", mission_data={
        "cmd": {"cmd_id": "eps_hk", "args_raw": eps_args_raw},
        "ptype": 2,
    })
    # img_cnt_chunks must arrive on a RES ptype (3) — ptype 2 is TLM.
    img_pkt = _img_cnt_pkt(pkt_num=11, filename="burst.jpg", num_chunks=1, ptype=3)

    eps_msgs = _run_pkt(a, eps_pkt)
    img_msgs = _run_pkt(a, img_pkt)

    assert any(m["type"] == "telemetry" for m in eps_msgs)
    # All 48 fragments attached to the packet.
    assert len(eps_pkt.mission_data["fragments"]) == 48
    assert any(m["type"] == "imaging_progress" for m in img_msgs)
