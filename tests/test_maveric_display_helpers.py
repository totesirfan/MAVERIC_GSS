"""Unit tests for shared MAVERIC display helpers."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from mav_gss_lib.missions.maveric.display_helpers import (
    md, has_decoded_gnc, ptype_of,
    unwrap_typed_arg_for_log, format_typed_arg_value, unwrap_typed_arg_for_display,
    is_nvg_sensor, is_bcd_display, is_adcs_tmp, is_nvg_heartbeat,
    is_gnc_mode, is_gnc_counters, is_bitfield, is_generic_dict,
)


class FakePkt:
    def __init__(self, mission_data=None):
        self.mission_data = mission_data


class DuckEpochMs:
    """Mimics schema._LazyEpochMs: not a dict, but supports `"ms" in v` / `v["ms"]`."""
    def __init__(self, ms): self.ms = ms
    def __contains__(self, k): return k in ("ms", "utc", "local")
    def __getitem__(self, k): return {"ms": self.ms}[k]


class MdTests(unittest.TestCase):
    def test_returns_mission_data(self):
        self.assertEqual(md(FakePkt({"a": 1})), {"a": 1})

    def test_missing_attr(self):
        self.assertEqual(md(object()), {})

    def test_none_mission_data(self):
        self.assertEqual(md(FakePkt(None)), {})


class PtypeOfTests(unittest.TestCase):
    def test_prefers_md_ptype_when_set(self):
        self.assertEqual(ptype_of({"ptype": 3, "cmd": {"pkt_type": 9}}), 3)

    def test_falls_back_to_cmd_pkt_type(self):
        self.assertEqual(ptype_of({"cmd": {"pkt_type": 2}}), 2)

    def test_returns_none_when_md_empty(self):
        self.assertIsNone(ptype_of({}))

    def test_returns_none_when_cmd_is_none(self):
        self.assertIsNone(ptype_of({"cmd": None}))


class HasDecodedGncTests(unittest.TestCase):
    def test_uses_fragments_with_gnc_domain(self):
        self.assertTrue(has_decoded_gnc(
            {"fragments": [{"domain": "gnc", "key": "STAT", "value": {}, "ts_ms": 0, "unit": ""}]}
        ))

    def test_empty(self):
        self.assertFalse(has_decoded_gnc({}))
        self.assertFalse(has_decoded_gnc({"fragments": []}))

    def test_only_non_gnc_fragments(self):
        self.assertFalse(has_decoded_gnc(
            {"fragments": [{"domain": "eps", "key": "V_BAT", "value": 7.6, "ts_ms": 0, "unit": "V"}]}
        ))

    def test_ignores_other_top_keys(self):
        self.assertFalse(has_decoded_gnc({"gnc": {"registers": {"STAT": {"decode_ok": True}}}}))


class UnwrapForLogTests(unittest.TestCase):
    def test_epoch_ms_dict(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "epoch_ms", "value": {"ms": 1234}}), 1234)

    def test_epoch_ms_lazy_wrapper(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "epoch_ms", "value": DuckEpochMs(9999)}), 9999)

    def test_epoch_ms_raw(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "epoch_ms", "value": 1234}), 1234)

    def test_epoch_ms_string_passthrough_no_crash(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "epoch_ms", "value": "24ms"}), "24ms")

    def test_blob_bytes(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "blob", "value": b"\x00\xff"}), "00ff")

    def test_blob_str(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "blob", "value": "already"}), "already")

    def test_passthrough(self):
        self.assertEqual(unwrap_typed_arg_for_log({"type": "int", "value": 5}), 5)
        self.assertEqual(unwrap_typed_arg_for_log({"type": "float", "value": 1.5}), 1.5)
        self.assertEqual(unwrap_typed_arg_for_log({"type": "str", "value": "hi"}), "hi")


class FormatTypedArgValueTests(unittest.TestCase):
    def test_epoch_ms_dict(self):
        self.assertEqual(format_typed_arg_value({"type": "epoch_ms", "value": {"ms": 1234}}), "1234")

    def test_epoch_ms_scalar(self):
        self.assertEqual(format_typed_arg_value({"type": "epoch_ms", "value": 1234}), "1234")

    def test_passthrough_int(self):
        self.assertEqual(format_typed_arg_value({"type": "int", "value": 5}), "5")

    def test_bytes_repr_preserved(self):
        # Legacy schema.format_arg_value used str() on bytes — CPython repr.
        self.assertEqual(format_typed_arg_value({"type": "blob", "value": b"\x00\xff"}), "b'\\x00\\xff'")

    def test_lazy_epoch_wrapper(self):
        self.assertEqual(format_typed_arg_value({"type": "epoch_ms", "value": DuckEpochMs(42)}), "42")

    def test_epoch_ms_string_passthrough_no_crash(self):
        self.assertEqual(format_typed_arg_value({"type": "epoch_ms", "value": "24ms"}), "24ms")


class UnwrapForDisplayTests(unittest.TestCase):
    def test_epoch_ms_hasattr_ms(self):
        class Lazy:
            ms = 42
        self.assertEqual(unwrap_typed_arg_for_display({"type": "epoch_ms", "value": Lazy()}), 42)

    def test_epoch_ms_dict(self):
        self.assertEqual(unwrap_typed_arg_for_display({"type": "epoch_ms", "value": {"ms": 99}}), 99)

    def test_blob_hex(self):
        self.assertEqual(unwrap_typed_arg_for_display({"type": "blob", "value": b"\x00\xff"}), "00ff")

    def test_scalar_passthrough(self):
        self.assertEqual(unwrap_typed_arg_for_display({"type": "int", "value": 7}), 7)


class PredicateTests(unittest.TestCase):
    def test_nvg_sensor(self):
        self.assertTrue(is_nvg_sensor({"sensor_id": 1, "values": []}))
        self.assertFalse(is_nvg_sensor({"sensor_id": 1}))
        self.assertFalse(is_nvg_sensor("x"))

    def test_bcd(self):
        self.assertTrue(is_bcd_display({"display": "12:34"}))
        self.assertFalse(is_bcd_display({"display": 1234}))
        self.assertFalse(is_bcd_display({}))

    def test_adcs_tmp(self):
        self.assertTrue(is_adcs_tmp({"celsius": 24.0}))
        self.assertFalse(is_adcs_tmp({}))

    def test_nvg_heartbeat_excludes_sensor_id(self):
        self.assertTrue(is_nvg_heartbeat({"label": "OK", "status": "nominal"}))
        self.assertFalse(is_nvg_heartbeat({"label": "OK", "status": "nom", "sensor_id": 1}))
        self.assertFalse(is_nvg_heartbeat({"label": "OK", "status": "nom", "mode": 1}))

    def test_gnc_mode_excludes_MODE_bitfield(self):
        self.assertTrue(is_gnc_mode({"mode_name": "SAFE", "mode": 1}))
        self.assertFalse(is_gnc_mode({"mode_name": "SAFE", "mode": 1, "MODE": 2}))

    def test_gnc_counters(self):
        self.assertTrue(is_gnc_counters({"sunspin": 1, "detumble": 2}))
        self.assertFalse(is_gnc_counters({"sunspin": 1}))

    def test_bitfield_with_MODE(self):
        self.assertTrue(is_bitfield({"MODE": 1}))

    def test_bitfield_with_bools(self):
        self.assertTrue(is_bitfield({"flag_a": True, "flag_b": False}))

    def test_bitfield_with_TARGET_ELEV(self):
        self.assertTrue(is_bitfield({"TARGET_ELEV": 45}))

    def test_bitfield_false(self):
        self.assertFalse(is_bitfield({"v": 5}))
        self.assertFalse(is_bitfield("x"))

    def test_generic_dict_catches_last(self):
        self.assertTrue(is_generic_dict({"arbitrary": 1}))
        self.assertFalse(is_generic_dict("x"))
        self.assertFalse(is_generic_dict([1, 2]))


if __name__ == "__main__":
    unittest.main()
