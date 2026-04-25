"""MaverPacketCodec tests.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import unittest

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.missions.maveric.errors import (
    DuplicateNodeId,
    DuplicatePtypeId,
    NodeIdOutOfRange,
    PtypeIdOutOfRange,
    UnknownNodeId,
    UnknownPtypeId,
)


class CodecConstructionTest(unittest.TestCase):
    def _ext(self, **overrides):
        base = {
            "nodes": {"NONE": 0, "LPPM": 1, "GS": 6},
            "ptypes": {"CMD": 1, "RES": 2},
            "gs_node": "GS",
        }
        base.update(overrides)
        return base

    def test_constructs_with_valid_extensions(self) -> None:
        codec = MaverPacketCodec(extensions=self._ext())
        self.assertEqual(codec.gs_node_id, 6)
        self.assertEqual(codec.node_id_for("LPPM"), 1)
        self.assertEqual(codec.node_name_for(1), "LPPM")
        self.assertEqual(codec.ptype_id_for("CMD"), 1)
        self.assertEqual(codec.ptype_name_for(2), "RES")

    def test_rejects_duplicate_node_id(self) -> None:
        with self.assertRaises(DuplicateNodeId):
            MaverPacketCodec(
                extensions=self._ext(nodes={"NONE": 0, "LPPM": 1, "GS": 1}),
            )

    def test_rejects_duplicate_ptype_id(self) -> None:
        with self.assertRaises(DuplicatePtypeId):
            MaverPacketCodec(
                extensions=self._ext(ptypes={"CMD": 1, "RES": 1}),
            )

    def test_rejects_node_out_of_range(self) -> None:
        with self.assertRaises(NodeIdOutOfRange):
            MaverPacketCodec(
                extensions=self._ext(nodes={"NONE": 0, "LPPM": 1, "GS": 999}),
            )

    def test_rejects_ptype_out_of_range(self) -> None:
        with self.assertRaises(PtypeIdOutOfRange):
            MaverPacketCodec(
                extensions=self._ext(ptypes={"CMD": 1, "RES": 300}),
            )


from mav_gss_lib.platform.spec import CommandHeader
from mav_gss_lib.platform.spec.errors import MissingRequiredHeaderField


class CompleteHeaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = MaverPacketCodec(
            extensions={
                "nodes": {"NONE": 0, "LPPM": 1, "GS": 6},
                "ptypes": {"CMD": 1, "RES": 2},
                "gs_node": "GS",
            }
        )

    def test_defaults_src_from_gs_node(self) -> None:
        h = CommandHeader(
            id="com_ping",
            fields={"dest": "LPPM", "echo": "NONE", "ptype": "CMD"},
        )
        completed = self.codec.complete_header(h)
        self.assertEqual(completed.fields["src"], "GS")
        self.assertEqual(completed.fields["dest"], "LPPM")
        self.assertEqual(completed.id, "com_ping")

    def test_preserves_explicit_src(self) -> None:
        h = CommandHeader(
            id="com_ping",
            fields={"src": "LPPM", "dest": "GS", "echo": "NONE", "ptype": "CMD"},
        )
        completed = self.codec.complete_header(h)
        self.assertEqual(completed.fields["src"], "LPPM")

    def test_raises_when_dest_missing(self) -> None:
        h = CommandHeader(id="com_ping", fields={"echo": "NONE", "ptype": "CMD"})
        with self.assertRaises(MissingRequiredHeaderField) as ctx:
            self.codec.complete_header(h)
        self.assertEqual(ctx.exception.field, "dest")

    def test_returned_header_is_new_instance(self) -> None:
        h = CommandHeader(
            id="com_ping",
            fields={"dest": "LPPM", "echo": "NONE", "ptype": "CMD"},
        )
        completed = self.codec.complete_header(h)
        self.assertIsNot(completed, h)
        self.assertNotIn("src", h.fields)


from mav_gss_lib.missions.maveric.wire_format import CommandFrame
from mav_gss_lib.platform.spec.errors import ArgsTooLong


class WrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = MaverPacketCodec(
            extensions={
                "nodes": {"NONE": 0, "LPPM": 1, "GS": 6, "EPS": 2},
                "ptypes": {"CMD": 1, "RES": 2, "ACK": 3, "TLM": 4, "FILE": 5},
                "gs_node": "GS",
            }
        )

    def _hdr(self, **overrides):
        base = {
            "src": "GS", "dest": "LPPM", "echo": "NONE", "ptype": "CMD",
        }
        base.update(overrides)
        return CommandHeader(id="com_ping", fields=base)

    def test_wrap_matches_legacy_command_frame_no_args(self) -> None:
        wire = self.codec.wrap(self._hdr(), b"")
        legacy = CommandFrame(
            src=6, dest=1, echo=0, pkt_type=1, cmd_id="com_ping", args_str=""
        ).to_bytes()
        self.assertEqual(bytes(wire), bytes(legacy))

    def test_wrap_matches_legacy_command_frame_with_args(self) -> None:
        args = b"100 200"
        hdr = self._hdr(dest="EPS", ptype="CMD")
        hdr = CommandHeader(id="ppm_delay", fields=hdr.fields)
        wire = self.codec.wrap(hdr, args)
        legacy = CommandFrame(
            src=6, dest=2, echo=0, pkt_type=1, cmd_id="ppm_delay",
            args_str="100 200",
        ).to_bytes()
        self.assertEqual(bytes(wire), bytes(legacy))

    def test_wrap_accepts_int_header_values(self) -> None:
        hdr = CommandHeader(
            id="com_ping",
            fields={"src": 6, "dest": 1, "echo": 0, "ptype": 1},
        )
        wire = self.codec.wrap(hdr, b"")
        self.assertEqual(wire[:4], bytes([6, 1, 0, 1]))

    def test_wrap_raises_on_args_too_long(self) -> None:
        with self.assertRaises(ArgsTooLong):
            self.codec.wrap(self._hdr(), b"x" * 256)

    def test_wrap_raises_on_unknown_node(self) -> None:
        hdr = CommandHeader(
            id="com_ping",
            fields={"src": "GS", "dest": "BOGUS", "echo": "NONE", "ptype": "CMD"},
        )
        with self.assertRaises(UnknownNodeId):
            self.codec.wrap(hdr, b"")

    def test_wrap_appends_crc16_le(self) -> None:
        wire = self.codec.wrap(self._hdr(), b"")
        # CRC-16 last 2 bytes, little-endian
        self.assertEqual(len(wire), 6 + len("com_ping") + 1 + 0 + 1 + 2)


from mav_gss_lib.platform.spec.errors import CrcMismatch


class UnwrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = MaverPacketCodec(
            extensions={
                "nodes": {"NONE": 0, "LPPM": 1, "GS": 6, "EPS": 2},
                "ptypes": {"CMD": 1, "RES": 2, "ACK": 3, "TLM": 4, "FILE": 5},
                "gs_node": "GS",
            }
        )

    def test_unwrap_returns_named_header_and_args_raw(self) -> None:
        # Build wire via legacy CommandFrame so the test is independent of wrap()
        legacy = CommandFrame(
            src=1, dest=6, echo=0, pkt_type=2, cmd_id="com_ping",
            args_str="ok",
        ).to_bytes()
        pkt = self.codec.unwrap(bytes(legacy))
        self.assertEqual(pkt.header["cmd_id"], "com_ping")
        self.assertEqual(pkt.header["src"], "LPPM")
        self.assertEqual(pkt.header["dest"], "GS")
        self.assertEqual(pkt.header["echo"], "NONE")
        self.assertEqual(pkt.header["ptype"], "RES")
        self.assertEqual(pkt.args_raw, b"ok")

    def test_unwrap_passes_through_unknown_byte_as_int(self) -> None:
        # Synthesize a frame with src=99 (no name in extensions)
        legacy = CommandFrame(
            src=99, dest=6, echo=0, pkt_type=2, cmd_id="com_ping",
        ).to_bytes()
        pkt = self.codec.unwrap(bytes(legacy))
        self.assertEqual(pkt.header["src"], 99)

    def test_unwrap_raises_on_bad_crc(self) -> None:
        legacy = bytearray(
            CommandFrame(
                src=1, dest=6, echo=0, pkt_type=2, cmd_id="com_ping",
            ).to_bytes()
        )
        legacy[-1] ^= 0xFF
        with self.assertRaises(CrcMismatch):
            self.codec.unwrap(bytes(legacy))

    def test_unwrap_strips_trailing_csp_crc32(self) -> None:
        legacy = CommandFrame(
            src=1, dest=6, echo=0, pkt_type=2, cmd_id="com_ping",
            args_str="ok",
        ).to_bytes()
        wire = bytes(legacy) + b"\x12\x34\x56\x78"
        pkt = self.codec.unwrap(wire)
        self.assertEqual(pkt.args_raw, b"ok")
        self.assertEqual(pkt.header.get("csp_crc32"), 0x12345678)

    def test_unwrap_short_payload_raises(self) -> None:
        with self.assertRaises(CrcMismatch):
            self.codec.unwrap(b"\x00\x00\x00")


class RoundTripParityTest(unittest.TestCase):
    """Byte-identity vs the legacy wire_format.CommandFrame."""

    def setUp(self) -> None:
        self.codec = MaverPacketCodec(
            extensions={
                "nodes": {"NONE": 0, "LPPM": 1, "EPS": 2, "UPPM": 3,
                          "HLNV": 4, "ASTR": 5, "GS": 6, "FTDI": 7},
                "ptypes": {"CMD": 1, "RES": 2, "ACK": 3, "TLM": 4, "FILE": 5},
                "gs_node": "GS",
            }
        )

    CASES = [
        ("com_ping", "GS", "LPPM", "NONE", "CMD", b""),
        ("com_ping", "GS", "EPS",  "NONE", "CMD", b""),
        ("ppm_delay", "GS", "LPPM", "NONE", "CMD", b"100"),
        ("eps_sw", "GS", "EPS", "NONE", "CMD", b"3 1"),
        ("cam_capture", "GS", "HLNV", "NONE", "CMD", b"img1.jpg 1 0 25 5000 1 80"),
        ("flash_read", "GS", "LPPM", "NONE", "CMD", b"0x1000 256"),
        ("nvg_get_1", "GS", "LPPM", "NONE", "CMD", b"4"),
        ("mtq_get_1", "GS", "LPPM", "NONE", "CMD", b"0 128"),
    ]

    def test_wrap_byte_identical_to_legacy(self) -> None:
        for cmd_id, src, dest, echo, ptype, args in self.CASES:
            with self.subTest(cmd=cmd_id, args=args):
                hdr = CommandHeader(
                    id=cmd_id,
                    fields={"src": src, "dest": dest, "echo": echo, "ptype": ptype},
                )
                wire = self.codec.wrap(hdr, args)
                legacy = CommandFrame(
                    src=self.codec.node_id_for(src),
                    dest=self.codec.node_id_for(dest),
                    echo=self.codec.node_id_for(echo),
                    pkt_type=self.codec.ptype_id_for(ptype),
                    cmd_id=cmd_id,
                    args_str=args.decode("ascii"),
                ).to_bytes()
                self.assertEqual(bytes(wire), bytes(legacy))

    def test_unwrap_inverts_wrap(self) -> None:
        for cmd_id, src, dest, echo, ptype, args in self.CASES:
            with self.subTest(cmd=cmd_id):
                hdr = CommandHeader(
                    id=cmd_id,
                    fields={"src": src, "dest": dest, "echo": echo, "ptype": ptype},
                )
                wire = self.codec.wrap(hdr, args)
                pkt = self.codec.unwrap(wire)
                self.assertEqual(pkt.header["cmd_id"], cmd_id)
                self.assertEqual(pkt.header["src"], src)
                self.assertEqual(pkt.header["dest"], dest)
                self.assertEqual(pkt.header["echo"], echo)
                self.assertEqual(pkt.header["ptype"], ptype)
                self.assertEqual(pkt.args_raw, args)


if __name__ == "__main__":
    unittest.main()
