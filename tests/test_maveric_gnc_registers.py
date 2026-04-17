"""Tests for MAVERIC TensorADCS register decoder.

Covers the 9 registers the GNC dashboard consumes. Sample fixtures are
the RES tokens observed in logs/text/downlink_20260417_120330_dashval.txt.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mav_gss_lib.missions.maveric.telemetry.gnc_registers import (
    MODE_NAMES,
    decode_from_cmd,
    decode_register,
    parse_type,
)


class TestParseType(unittest.TestCase):

    def test_array_type(self):
        self.assertEqual(parse_type("float[3]"), ("float", 3))
        self.assertEqual(parse_type("uint8[4]"), ("uint8", 4))
        self.assertEqual(parse_type("int16[2]"), ("int16", 2))
        self.assertEqual(parse_type("char[140]"), ("char", 140))

    def test_scalar_type(self):
        self.assertEqual(parse_type("float"), ("float", 1))
        self.assertEqual(parse_type("uint8"), ("uint8", 1))

    def test_whitespace_tolerant(self):
        self.assertEqual(parse_type("uint8 [4]"), ("uint8", 4))


class TestSimpleCoercion(unittest.TestCase):

    def test_float_array(self):
        d = decode_register(0, 103, ["0.000000", "0.000000", "0.000000"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.name, "MTQ_USER")
        self.assertEqual(d.value, [0.0, 0.0, 0.0])

    def test_float_array_nonzero(self):
        d = decode_register(0, 136, ["0.1", "-0.05", "0.02"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.name, "RATE")
        self.assertAlmostEqual(d.value[0], 0.1)
        self.assertAlmostEqual(d.value[1], -0.05)
        self.assertAlmostEqual(d.value[2], 0.02)

    def test_unknown_register_preserves_tokens(self):
        d = decode_register(9, 99, ["1", "2", "3"])
        self.assertFalse(d.decode_ok)
        self.assertEqual(d.name, "UNKNOWN_9_99")
        self.assertEqual(d.value, ["1", "2", "3"])

    def test_short_token_list(self):
        d = decode_register(0, 103, ["1.0", "2.0"])  # needs 3 floats
        self.assertFalse(d.decode_ok)
        self.assertIn("expected 3 tokens", d.decode_error)


class TestTimeBCDDecoder(unittest.TestCase):
    """TIME (0, 5) — BCD HH/MM/SS in bytes[3..1] little-endian."""

    def test_sample_packet_46(self):
        # Wire: 0 5 0 39 38 0 → bytes_le [0, 39, 38, 0]
        d = decode_register(0, 5, ["0", "39", "38", "0"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["hour"], 0)
        self.assertEqual(d.value["minute"], 26)
        self.assertEqual(d.value["second"], 27)
        self.assertEqual(d.value["display"], "00:26:27")

    def test_noon_twenty_three(self):
        # 12:34:56 encoded: byte3=0x12, byte2=0x34, byte1=0x56
        d = decode_register(0, 5, ["0", "86", "52", "18"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["display"], "12:34:56")


class TestDateBCDDecoder(unittest.TestCase):
    """DATE (0, 6) — BCD YY/MM/DD + weekday."""

    def test_sample_packet_50(self):
        # Wire: 0 6 0 1 1 32 → bytes_le [0, 1, 1, 0x20]
        d = decode_register(0, 6, ["0", "1", "1", "32"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["year_yy"], 20)
        self.assertEqual(d.value["year"], 2020)
        self.assertEqual(d.value["month"], 1)
        self.assertEqual(d.value["day"], 1)
        self.assertEqual(d.value["weekday"], 0)
        self.assertEqual(d.value["display"], "2020-01-01")


class TestAdcsTmpDecoder(unittest.TestCase):
    """ADCS_TMP (0, 148) — BRDTMP * 150 / 32768 °C."""

    def test_zero_sample(self):
        # Wire: 0 148 0 0 → [0, 0]
        d = decode_register(0, 148, ["0", "0"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["brdtmp"], 0)
        self.assertEqual(d.value["celsius"], 0.0)
        self.assertFalse(d.value["comm_fault"])

    def test_nominal_warm(self):
        # 20 °C → BRDTMP ≈ 20 * 32768 / 150 ≈ 4369
        d = decode_register(0, 148, ["4369", "0"])
        self.assertTrue(d.decode_ok)
        self.assertAlmostEqual(d.value["celsius"], 20.0, places=1)

    def test_negative(self):
        # -20 °C → BRDTMP ≈ -4369
        d = decode_register(0, 148, ["-4369", "0"])
        self.assertTrue(d.decode_ok)
        self.assertAlmostEqual(d.value["celsius"], -20.0, places=1)

    def test_comm_fault_sentinel(self):
        # BRDTMP = -1 (0xFFFF as int16) per manual
        d = decode_register(0, 148, ["-1", "0"])
        self.assertTrue(d.decode_ok)
        self.assertTrue(d.value["comm_fault"])
        self.assertIsNone(d.value["celsius"])


class TestFssTmpDecoder(unittest.TestCase):
    """FSS_TMP1 (0, 153) — Manual Eq. 6-3: °C = FSSxTMP × 0.03125."""

    def test_zero_raw(self):
        d = decode_register(0, 153, ["0", "0"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["fss0_raw"], 0)
        self.assertEqual(d.value["fss0_celsius"], 0.0)
        self.assertEqual(d.value["fss1_celsius"], 0.0)

    def test_nominal_warm(self):
        # 20°C → raw = 20 / 0.03125 = 640
        d = decode_register(0, 153, ["640", "800"])
        self.assertAlmostEqual(d.value["fss0_celsius"], 20.0, places=3)
        self.assertAlmostEqual(d.value["fss1_celsius"], 25.0, places=3)

    def test_negative_cold(self):
        d = decode_register(0, 153, ["-640", "0"])
        self.assertAlmostEqual(d.value["fss0_celsius"], -20.0, places=3)


class TestMagUnitIsNanoTesla(unittest.TestCase):
    """Sanity — MAG stores unit string as 'nT' despite manual's 'µT'
    because wire data is nanotesla (verified against sample log)."""

    def test_mag_unit_is_nt(self):
        d = decode_register(0, 159, ["-31320.302963", "0.240334", "0.0"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.unit, "nT")
        self.assertAlmostEqual(d.value[0], -31320.302963, places=3)


class TestStatBitfieldDecoder(unittest.TestCase):
    """STAT (0, 128) — mode + error/status flags."""

    def test_all_zeros_sample(self):
        # Wire: 0 128 0 0 0 0
        d = decode_register(0, 128, ["0", "0", "0", "0"])
        self.assertTrue(d.decode_ok)
        self.assertEqual(d.value["MODE"], 0)
        self.assertEqual(d.value["MODE_NAME"], "Safe")
        # All error flags false
        for k in ("HERR", "SERR", "WDT", "UV", "OC", "OT"):
            self.assertFalse(d.value[k], f"{k} should be false")
        # All status flags false
        for k in ("TLE", "DES", "SUN", "TGL", "TUMB", "AME", "CUSSV", "EKF"):
            self.assertFalse(d.value[k], f"{k} should be false")

    def test_mode_sun_spin(self):
        # MODE=2 (Sun Spin) in byte[0], all other bytes zero
        d = decode_register(0, 128, ["2", "0", "0", "0"])
        self.assertEqual(d.value["MODE"], 2)
        self.assertEqual(d.value["MODE_NAME"], "Sun Spin")

    def test_mode_target_tracking(self):
        d = decode_register(0, 128, ["6", "0", "0", "0"])
        self.assertEqual(d.value["MODE"], 6)
        self.assertEqual(d.value["MODE_NAME"], "Target Tracking")

    def test_herr_bit(self):
        # HERR is bit 31 -> byte[3] bit 7 -> byte[3] == 0x80
        d = decode_register(0, 128, ["0", "0", "0", "128"])
        self.assertTrue(d.value["HERR"])
        self.assertFalse(d.value["SERR"])

    def test_sun_and_ekf(self):
        # byte[1] bits: SUN=5, EKF=0. SUN+EKF => 0b00100001 = 0x21 = 33
        d = decode_register(0, 128, ["0", "33", "0", "0"])
        self.assertTrue(d.value["SUN"])
        self.assertTrue(d.value["EKF"])
        self.assertFalse(d.value["TLE"])
        self.assertFalse(d.value["TUMB"])

    def test_all_mode_names_cover_3_bit_space(self):
        for n in range(8):
            self.assertIn(n, MODE_NAMES)


class TestActErrBitfield(unittest.TestCase):
    """ACT_ERR (0, 129) — MTQ and CMG error bits."""

    def test_all_zeros_sample(self):
        d = decode_register(0, 129, ["0", "0", "0", "0"])
        self.assertTrue(d.decode_ok)
        for k in ("MTQ0", "MTQ1", "MTQ2", "CMG0", "CMG1", "CMG2", "CMG3"):
            self.assertFalse(d.value[k])

    def test_mtq1_set(self):
        # MTQ1 = byte[1] bit 1 = 0b00000010 = 2
        d = decode_register(0, 129, ["0", "2", "0", "0"])
        self.assertTrue(d.value["MTQ1"])
        self.assertFalse(d.value["MTQ0"])
        self.assertFalse(d.value["MTQ2"])

    def test_cmg0_and_mtq2(self):
        d = decode_register(0, 129, ["1", "4", "0", "0"])
        self.assertTrue(d.value["CMG0"])
        self.assertTrue(d.value["MTQ2"])


class TestSenErrBitfield(unittest.TestCase):
    """SEN_ERR (0, 130) — FSS/MAG/IMU/STR error bits."""

    def test_sample_packet_66(self):
        # Wire: 0 130 0 0 12 0 → byte[2] = 12 = 0b00001100
        # Bits set: byte[2] bit 2 (IMU2), byte[2] bit 3 (IMU3)
        d = decode_register(0, 130, ["0", "0", "12", "0"])
        self.assertTrue(d.decode_ok)
        self.assertTrue(d.value["IMU2"])
        self.assertTrue(d.value["IMU3"])
        self.assertFalse(d.value["IMU0"])
        self.assertFalse(d.value["IMU1"])
        # All other sensors nominal
        for k in ("FSS0", "FSS1", "FSS2", "FSS3", "FSS4", "FSS5"):
            self.assertFalse(d.value[k])
        for k in ("MAG0", "MAG1", "MAG2", "MAG3", "MAG4", "MAG5"):
            self.assertFalse(d.value[k])
        for k in ("STR0", "STR1"):
            self.assertFalse(d.value[k])

    def test_fss5_only(self):
        # FSS5 = byte[0] bit 5 = 0b00100000 = 32
        d = decode_register(0, 130, ["32", "0", "0", "0"])
        self.assertTrue(d.value["FSS5"])
        self.assertFalse(d.value["FSS4"])

    def test_mag_and_imu(self):
        # MAG0 = byte[1] bit 0 = 1; IMU0 = byte[2] bit 0 = 1
        d = decode_register(0, 130, ["0", "1", "1", "0"])
        self.assertTrue(d.value["MAG0"])
        self.assertTrue(d.value["IMU0"])
        self.assertFalse(d.value["MAG1"])
        self.assertFalse(d.value["IMU1"])


class TestDecodeFromCmd(unittest.TestCase):
    """decode_from_cmd glue — extracts tokens from a parsed cmd dict."""

    def _make_cmd(self, cmd_id: str, module: int, register: int, data_tokens: list[str]) -> dict:
        """Mirror the structure rx_ops.parse_packet produces."""
        typed = [
            {"name": "Module",   "type": "str", "value": str(module)},
            {"name": "Register", "type": "str", "value": str(register)},
        ]
        extras: list[str] = []
        if data_tokens:
            typed.append({"name": "Reg Data", "type": "str", "value": data_tokens[0]})
            extras = list(data_tokens[1:])
        return {"cmd_id": cmd_id, "typed_args": typed, "extra_args": extras}

    def test_mtq_get_1_time_sample(self):
        cmd = self._make_cmd("mtq_get_1", 0, 5, ["0", "39", "38", "0"])
        out = decode_from_cmd(cmd)
        self.assertIsNotNone(out)
        self.assertIn("TIME", out)
        self.assertEqual(out["TIME"]["value"]["display"], "00:26:27")

    def test_mtq_get_1_stat_sample(self):
        cmd = self._make_cmd("mtq_get_1", 0, 128, ["0", "0", "0", "0"])
        out = decode_from_cmd(cmd)
        self.assertIn("STAT", out)
        self.assertEqual(out["STAT"]["value"]["MODE_NAME"], "Safe")

    def test_mtq_get_1_sen_err_sample(self):
        cmd = self._make_cmd("mtq_get_1", 0, 130, ["0", "0", "12", "0"])
        out = decode_from_cmd(cmd)
        self.assertIn("SEN_ERR", out)
        self.assertTrue(out["SEN_ERR"]["value"]["IMU2"])

    def test_non_mtq_command_returns_none(self):
        cmd = self._make_cmd("mtq_read_all", 0, 0, [])
        self.assertIsNone(decode_from_cmd(cmd))

    def test_missing_module_register_returns_none(self):
        cmd = {"cmd_id": "mtq_get_1", "typed_args": [], "extra_args": []}
        self.assertIsNone(decode_from_cmd(cmd))

    def test_unknown_register_still_returns_entry(self):
        # Module/register pair definitely absent from the catalog.
        cmd = self._make_cmd("mtq_get_1", 9, 99, ["1.0", "2.0", "3.0"])
        out = decode_from_cmd(cmd)
        self.assertIsNotNone(out)
        self.assertIn("UNKNOWN_9_99", out)
        self.assertFalse(out["UNKNOWN_9_99"]["decode_ok"])


if __name__ == "__main__":
    unittest.main()
