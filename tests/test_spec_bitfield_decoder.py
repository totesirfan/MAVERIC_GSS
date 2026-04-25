import unittest

from mav_gss_lib.platform.spec.bitfield import BitfieldEntry, BitfieldType
from mav_gss_lib.platform.spec.cursor import BitCursor
from mav_gss_lib.platform.spec.parameter_types import EnumeratedParameterType, EnumValue
from mav_gss_lib.platform.spec.runtime import BitfieldDecoder


class TestBitfieldDecoder(unittest.TestCase):
    def test_decode_emits_one_value_per_slice(self):
        bf = BitfieldType(
            name="STAT", size_bits=8, byte_order="little",
            entry_list=(
                BitfieldEntry(name="thr_ok", bits=(0, 0), kind="bool"),
                BitfieldEntry(name="err_count", bits=(1, 4), kind="uint"),
                BitfieldEntry(name="reserved", bits=(5, 7), kind="uint"),
            ),
        )
        decoder = BitfieldDecoder(types={})
        # 0b01101001 = 0x69 — thr_ok=1, err_count=0b0100=4, reserved=0b011=3
        cursor = BitCursor(b"\x69")
        decoded = decoder.decode(bf, cursor)
        self.assertEqual(decoded["thr_ok"], True)
        self.assertEqual(decoded["err_count"], 4)
        self.assertEqual(decoded["reserved"], 3)

    def test_int_slice_sign_extends(self):
        bf = BitfieldType(
            name="X", size_bits=8,
            entry_list=(BitfieldEntry(name="v", bits=(0, 3), kind="int"),),
        )
        decoder = BitfieldDecoder(types={})
        cursor = BitCursor(b"\x0f")  # 0b1111 in low 4 bits
        decoded = decoder.decode(bf, cursor)
        self.assertEqual(decoded["v"], -1)

    def test_enum_slice_synthesizes_name(self):
        types = {
            "GncMode": EnumeratedParameterType(
                name="GncMode", size_bits=8,
                values=(EnumValue(raw=0, label="Safe"), EnumValue(raw=1, label="Auto")),
            ),
        }
        bf = BitfieldType(
            name="STAT", size_bits=8,
            entry_list=(
                BitfieldEntry(name="mode", bits=(0, 1), kind="enum", enum_ref="GncMode"),
            ),
        )
        decoder = BitfieldDecoder(types=types)
        cursor = BitCursor(b"\x01")  # mode=1
        decoded = decoder.decode(bf, cursor)
        self.assertEqual(decoded["mode"], 1)
        self.assertEqual(decoded["mode_name"], "Auto")

    def test_enum_slice_unknown_raw_emits_unknown_label(self):
        types = {
            "GncMode": EnumeratedParameterType(
                name="GncMode", size_bits=8,
                values=(EnumValue(raw=0, label="Safe"),),
            ),
        }
        bf = BitfieldType(
            name="STAT", size_bits=8,
            entry_list=(
                BitfieldEntry(name="mode", bits=(0, 1), kind="enum", enum_ref="GncMode"),
            ),
        )
        decoder = BitfieldDecoder(types=types)
        cursor = BitCursor(b"\x03")  # mode=3 (not in table)
        decoded = decoder.decode(bf, cursor)
        self.assertEqual(decoded["mode"], 3)
        self.assertEqual(decoded["mode_name"], "UNKNOWN_3")


if __name__ == "__main__":
    unittest.main()
