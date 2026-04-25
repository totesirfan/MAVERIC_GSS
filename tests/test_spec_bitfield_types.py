import unittest

from mav_gss_lib.platform.spec.bitfield import BitfieldEntry, BitfieldType


class TestBitfieldDataclasses(unittest.TestCase):
    def test_bitfield_entry_holds_lo_hi_inclusive(self):
        e = BitfieldEntry(name="mode", bits=(0, 2), kind="enum", enum_ref="GncMode")
        self.assertEqual(e.bits, (0, 2))
        self.assertEqual(e.kind, "enum")
        self.assertEqual(e.enum_ref, "GncMode")

    def test_bitfield_type_carries_size_and_entries(self):
        t = BitfieldType(
            name="STAT",
            size_bits=32,
            byte_order="little",
            entry_list=(
                BitfieldEntry(name="thr_ok", bits=(0, 0), kind="bool"),
                BitfieldEntry(name="err_count", bits=(1, 8), kind="uint"),
            ),
        )
        self.assertEqual(t.size_bits, 32)
        self.assertEqual(len(t.entry_list), 2)


if __name__ == "__main__":
    unittest.main()
