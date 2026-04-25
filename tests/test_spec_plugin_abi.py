import unittest

from mav_gss_lib.platform.spec import (
    BUILT_IN_PARAMETER_TYPES,
    CalibratorRuntime,
    EnumeratedParameterType,
    EnumValue,
    IntegerParameterType,
    MissingPluginError,
    PythonCalibrator,
    StringParameterType,
)


class TestPluginAbi(unittest.TestCase):
    def test_int_calibrator_ok(self):
        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16, signed=True,
                calibrator=PythonCalibrator(callable_ref="m.scale", unit="V"),
            )
        }
        rt = CalibratorRuntime(types=types, plugins={"m.scale": lambda raw: (raw / 1000.0, "V")})
        value, unit = rt.apply("V", 1500)
        self.assertAlmostEqual(value, 1.5)
        self.assertEqual(unit, "V")

    def test_missing_plugin_rejected_at_construction(self):
        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16,
                calibrator=PythonCalibrator(callable_ref="m.missing"),
            )
        }
        with self.assertRaises(MissingPluginError):
            CalibratorRuntime(types=types, plugins={})

    def test_plugin_returning_dict_value(self):
        def make_dict(raw):
            return ({"raw": raw, "scaled": raw * 2}, "")
        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16,
                calibrator=PythonCalibrator(callable_ref="m.dict"),
            )
        }
        rt = CalibratorRuntime(types=types, plugins={"m.dict": make_dict})
        value, _ = rt.apply("V", 21)
        self.assertEqual(value, {"raw": 21, "scaled": 42})


if __name__ == "__main__":
    unittest.main()
