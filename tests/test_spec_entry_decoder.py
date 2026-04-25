import unittest

from mav_gss_lib.platform.spec.bitfield import BitfieldEntry, BitfieldType
from mav_gss_lib.platform.spec.calibrator_runtime import CalibratorRuntime
from mav_gss_lib.platform.spec.calibrators import PolynomialCalibrator
from mav_gss_lib.platform.spec.containers import (
    ParameterRefEntry,
    RepeatEntry,
    SequenceContainer,
)
from mav_gss_lib.platform.spec.cursor import TokenCursor
from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    IntegerParameterType,
)
from mav_gss_lib.platform.spec.runtime import EntryDecoder, TypeCodec


class TestEntryDecoder(unittest.TestCase):
    def test_parameter_ref_entry_emits_one_fragment(self):
        types = dict(BUILT_IN_PARAMETER_TYPES)
        types["V_volts"] = IntegerParameterType(
            name="V_volts", size_bits=16, signed=True,
            calibrator=PolynomialCalibrator(coefficients=(0.0, 0.001), unit="V"),
        )
        codec = TypeCodec(types=types)
        cal = CalibratorRuntime(types=types, plugins={})
        decoder = EntryDecoder(types=types, codec=codec, calibrators=cal, bitfields={})
        container = SequenceContainer(
            name="x",
            entry_list=(ParameterRefEntry(name="V_BUS", type_ref="V_volts"),),
            domain="eps",
        )
        cursor = TokenCursor(b"1500")
        decoded_into: dict = {}
        fragments = list(decoder.walk(container, cursor, now_ms=42, decoded_into=decoded_into))
        self.assertEqual(len(fragments), 1)
        f = fragments[0]
        self.assertEqual(f.domain, "eps")
        self.assertEqual(f.key, "V_BUS")
        self.assertAlmostEqual(f.value, 1.5)
        self.assertEqual(f.unit, "V")
        self.assertEqual(decoded_into["V_BUS"], 1500)  # raw value cached for dispatch

    def test_emit_false_decodes_but_no_fragment(self):
        types = dict(BUILT_IN_PARAMETER_TYPES)
        codec = TypeCodec(types=types)
        cal = CalibratorRuntime(types=types, plugins={})
        decoder = EntryDecoder(types=types, codec=codec, calibrators=cal, bitfields={})
        container = SequenceContainer(
            name="x",
            entry_list=(ParameterRefEntry(name="dispatch_key", type_ref="u8", emit=False),),
            domain="d",
        )
        cursor = TokenCursor(b"5")
        decoded_into: dict = {}
        fragments = list(decoder.walk(container, cursor, now_ms=42, decoded_into=decoded_into))
        self.assertEqual(fragments, [])
        self.assertEqual(decoded_into["dispatch_key"], 5)

    def test_repeat_entry_count_to_end(self):
        types = dict(BUILT_IN_PARAMETER_TYPES)
        codec = TypeCodec(types=types)
        cal = CalibratorRuntime(types=types, plugins={})
        decoder = EntryDecoder(types=types, codec=codec, calibrators=cal, bitfields={})
        container = SequenceContainer(
            name="x",
            entry_list=(
                RepeatEntry(
                    entry=ParameterRefEntry(name="slot", type_ref="ascii_token"),
                    count_kind="to_end",
                ),
            ),
            domain="d",
        )
        cursor = TokenCursor(b"alpha beta gamma")
        decoded_into: dict = {}
        fragments = list(decoder.walk(container, cursor, now_ms=0, decoded_into=decoded_into))
        self.assertEqual([f.value for f in fragments], ["alpha", "beta", "gamma"])

    def test_bitfield_entry_one_fragment_dict_value(self):
        types = dict(BUILT_IN_PARAMETER_TYPES)
        bitfields = {
            "STAT_REG": BitfieldType(
                name="STAT_REG", size_bits=8,
                entry_list=(
                    BitfieldEntry(name="thr_ok", bits=(0, 0), kind="bool"),
                    BitfieldEntry(name="err_count", bits=(1, 4), kind="uint"),
                ),
            ),
        }
        codec = TypeCodec(types=types)
        cal = CalibratorRuntime(types=types, plugins={})
        decoder = EntryDecoder(types=types, codec=codec, calibrators=cal, bitfields=bitfields)
        container = SequenceContainer(
            name="x",
            entry_list=(ParameterRefEntry(name="STAT", type_ref="STAT_REG"),),
            domain="gnc",
            layout="binary",
        )
        from mav_gss_lib.platform.spec.cursor import BitCursor
        cursor = BitCursor(b"\x09")  # 0b00001001 → thr_ok=1, err_count=4
        decoded_into: dict = {}
        fragments = list(decoder.walk(container, cursor, now_ms=0, decoded_into=decoded_into))
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].key, "STAT")
        self.assertEqual(fragments[0].value, {"thr_ok": True, "err_count": 4})


    def test_ascii_dynamic_ref_binary_caches_raw(self):
        """Reproduces the UnboundLocalError on the ASCII layout dynamic_ref path."""
        from mav_gss_lib.platform.spec.parameter_types import BinaryParameterType
        types = dict(BUILT_IN_PARAMETER_TYPES)
        types["ChunkData"] = BinaryParameterType(
            name="ChunkData", size_kind="dynamic_ref", size_ref="chunk_len",
        )
        codec = TypeCodec(types=types)
        cal = CalibratorRuntime(types=types, plugins={})
        decoder = EntryDecoder(types=types, codec=codec, calibrators=cal, bitfields={})
        container = SequenceContainer(
            name="x",
            entry_list=(
                ParameterRefEntry(name="chunk_len", type_ref="u8", emit=False),
                ParameterRefEntry(name="data", type_ref="ChunkData"),
            ),
            domain="d",
        )
        cursor = TokenCursor(b"3 hello")
        decoded_into: dict = {}
        fragments = list(decoder.walk(container, cursor, now_ms=0, decoded_into=decoded_into))
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].key, "data")
        # blob is b"hello"; trimmed to first 3 bytes by the dynamic_ref size
        self.assertEqual(fragments[0].value, b"hel")


if __name__ == "__main__":
    unittest.main()
