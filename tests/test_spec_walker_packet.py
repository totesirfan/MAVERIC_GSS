import unittest
from dataclasses import dataclass

from mav_gss_lib.platform.spec.bitfield import BitfieldEntry, BitfieldType
from mav_gss_lib.platform.spec.containers import (
    Comparison,
    ParameterRefEntry,
    RestrictionCriteria,
    SequenceContainer,
)
from mav_gss_lib.platform.spec.mission import Mission, MissionHeader
from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    EnumeratedParameterType,
    EnumValue,
)
from mav_gss_lib.platform.spec.parameters import Parameter
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker
from mav_gss_lib.platform.spec.walker_packet import WalkerPacket


@dataclass(frozen=True, slots=True)
class _StubPacket:
    args_raw: bytes
    header: dict


class TestWalkerPacket(unittest.TestCase):
    def test_runtime_checkable_against_stub_with_required_fields(self):
        p = _StubPacket(args_raw=b"\x01\x02", header={"cmd_id": "eps_hk", "ptype": "RES"})
        self.assertIsInstance(p, WalkerPacket)

    def test_runtime_checkable_rejects_missing_args_raw(self):
        @dataclass(frozen=True, slots=True)
        class NoArgs:
            header: dict

        self.assertNotIsInstance(NoArgs(header={}), WalkerPacket)


def _build_mission(
    *,
    bitfield: BitfieldType,
    parameter: Parameter,
    binary_container: SequenceContainer,
    ascii_container: SequenceContainer,
    extra_types: dict | None = None,
) -> Mission:
    types = dict(BUILT_IN_PARAMETER_TYPES)
    if extra_types:
        types.update(extra_types)
    return Mission(
        id="test_mission",
        name="test_mission",
        header=MissionHeader(version="0", date="2026-01-01"),
        parameter_types=types,
        parameters={parameter.name: parameter},
        bitfield_types={bitfield.name: bitfield},
        sequence_containers={
            binary_container.name: binary_container,
            ascii_container.name: ascii_container,
        },
        meta_commands={},
    )


class TestBitfieldDecodeUnderBothLayouts(unittest.TestCase):
    """Phase 1 of XTCE 1.3 alignment: bitfield types decode identically
    under both binary and ascii_tokens layouts. The wire transport (raw
    bytes vs. whitespace-delimited u8 tokens) is orthogonal to type-system
    interpretation.
    """

    def test_simple_bitfield_decodes_identically_under_both_layouts(self):
        # 32-bit register, byte_order=little:
        # document-order byte 0 is the LSB byte → register = 0x00008001.
        # MODE (bits 0..6) = 1, FLAG7 (bit 7) = 0, B15 (bit 15) = 1.
        bf = BitfieldType(
            name="MyReg",
            size_bits=32,
            byte_order="little",
            entry_list=(
                BitfieldEntry(name="MODE", bits=(0, 6), kind="uint"),
                BitfieldEntry(name="FLAG7", bits=(7, 7), kind="bool"),
                BitfieldEntry(name="B15", bits=(15, 15), kind="bool"),
            ),
        )
        param = Parameter(name="STAT", type_ref="MyReg", domain="reg")
        rc_binary = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="bin_pkt"),),
        )
        rc_ascii = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="ascii_pkt"),),
        )
        binary_container = SequenceContainer(
            name="binary_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="MyReg"),),
            restriction_criteria=rc_binary,
            layout="binary",
            domain="reg",
        )
        ascii_container = SequenceContainer(
            name="ascii_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="MyReg"),),
            restriction_criteria=rc_ascii,
            layout="ascii_tokens",
            domain="reg",
        )
        mission = _build_mission(
            bitfield=bf,
            parameter=param,
            binary_container=binary_container,
            ascii_container=ascii_container,
        )
        walker = DeclarativeWalker(mission, plugins={})

        bin_pkt = _StubPacket(
            args_raw=b"\x01\x80\x00\x00", header={"cmd_id": "bin_pkt"},
        )
        ascii_pkt = _StubPacket(
            args_raw=b"1 128 0 0", header={"cmd_id": "ascii_pkt"},
        )

        bin_updates = list(walker.extract(bin_pkt, now_ms=0))
        ascii_updates = list(walker.extract(ascii_pkt, now_ms=0))

        self.assertEqual(len(bin_updates), 1)
        self.assertEqual(len(ascii_updates), 1)
        self.assertEqual(bin_updates[0].name, "reg.STAT")
        self.assertEqual(ascii_updates[0].name, "reg.STAT")
        expected = {"MODE": 1, "FLAG7": False, "B15": True}
        self.assertEqual(bin_updates[0].value, expected)
        self.assertEqual(ascii_updates[0].value, expected)
        self.assertEqual(bin_updates[0].value, ascii_updates[0].value)

    def test_realistic_bitfield_with_enum_and_bools_under_both_layouts(self):
        # Mirrors the shape of a real status register: an enum mode slice in
        # the low bits, a handful of bools, an unsigned counter, all packed
        # into a 32-bit little-endian register. Test does not import any
        # mission package — just exercises the same shape declaratively.
        ctrl_mode_t = EnumeratedParameterType(
            name="CtrlMode",
            size_bits=8,
            values=(
                EnumValue(raw=0, label="IDLE"),
                EnumValue(raw=1, label="RUN"),
                EnumValue(raw=2, label="SAFE"),
            ),
        )
        bf = BitfieldType(
            name="StatReg",
            size_bits=32,
            byte_order="little",
            entry_list=(
                BitfieldEntry(
                    name="ctrl_mode", bits=(0, 2), kind="enum", enum_ref="CtrlMode",
                ),
                BitfieldEntry(name="run_ok", bits=(3, 3), kind="bool"),
                BitfieldEntry(name="fault", bits=(4, 4), kind="bool"),
                BitfieldEntry(name="self_test", bits=(5, 5), kind="bool"),
                BitfieldEntry(name="err_cnt", bits=(8, 15), kind="uint"),
            ),
        )
        param = Parameter(name="STAT", type_ref="StatReg", domain="reg")
        rc_binary = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="bin_pkt"),),
        )
        rc_ascii = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="ascii_pkt"),),
        )
        binary_container = SequenceContainer(
            name="binary_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="StatReg"),),
            restriction_criteria=rc_binary,
            layout="binary",
            domain="reg",
        )
        ascii_container = SequenceContainer(
            name="ascii_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="StatReg"),),
            restriction_criteria=rc_ascii,
            layout="ascii_tokens",
            domain="reg",
        )
        mission = _build_mission(
            bitfield=bf,
            parameter=param,
            binary_container=binary_container,
            ascii_container=ascii_container,
            extra_types={"CtrlMode": ctrl_mode_t},
        )
        walker = DeclarativeWalker(mission, plugins={})

        # Build a register value = 0x00057E + (err_cnt=0x2A << 8) = 0x2A057E? Easier:
        # Choose: ctrl_mode=1 (RUN), run_ok=1, fault=0, self_test=1, err_cnt=42.
        # Low byte: bits 0..2=001, bit3=1, bit4=0, bit5=1, bits6,7=0 → 0b00101001 = 0x29.
        # Next byte: err_cnt low 8 bits = 42 = 0x2A.
        # High two bytes = 0.
        bin_pkt = _StubPacket(
            args_raw=b"\x29\x2A\x00\x00", header={"cmd_id": "bin_pkt"},
        )
        ascii_pkt = _StubPacket(
            args_raw=b"41 42 0 0", header={"cmd_id": "ascii_pkt"},
        )

        bin_updates = list(walker.extract(bin_pkt, now_ms=0))
        ascii_updates = list(walker.extract(ascii_pkt, now_ms=0))

        self.assertEqual(len(bin_updates), 1)
        self.assertEqual(len(ascii_updates), 1)

        expected = {
            "ctrl_mode": 1,
            "ctrl_mode_name": "RUN",
            "run_ok": True,
            "fault": False,
            "self_test": True,
            "err_cnt": 42,
        }
        self.assertEqual(bin_updates[0].value, expected)
        self.assertEqual(ascii_updates[0].value, expected)
        self.assertEqual(bin_updates[0].value, ascii_updates[0].value)

    def test_ascii_bitfield_token_out_of_u8_range_raises(self):
        # An ascii_tokens register should not silently truncate `256` or `-1`
        # to a low byte — that hides spacecraft-side bugs. The walker must
        # raise ValueError naming the offending bitfield.
        bf = BitfieldType(
            name="MyReg",
            size_bits=32,
            byte_order="little",
            entry_list=(
                BitfieldEntry(name="MODE", bits=(0, 6), kind="uint"),
            ),
        )
        param = Parameter(name="STAT", type_ref="MyReg", domain="reg")
        rc_binary = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="bin_pkt"),),
        )
        rc_ascii = RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="ascii_pkt"),),
        )
        binary_container = SequenceContainer(
            name="binary_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="MyReg"),),
            restriction_criteria=rc_binary,
            layout="binary",
            domain="reg",
        )
        ascii_container = SequenceContainer(
            name="ascii_container",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="MyReg"),),
            restriction_criteria=rc_ascii,
            layout="ascii_tokens",
            domain="reg",
        )
        mission = _build_mission(
            bitfield=bf,
            parameter=param,
            binary_container=binary_container,
            ascii_container=ascii_container,
        )
        walker = DeclarativeWalker(mission, plugins={})

        bad_pkt = _StubPacket(
            args_raw=b"256 0 0 0", header={"cmd_id": "ascii_pkt"},
        )
        with self.assertRaisesRegex(ValueError, r"MyReg"):
            list(walker.extract(bad_pkt, now_ms=0))


if __name__ == "__main__":
    unittest.main()
