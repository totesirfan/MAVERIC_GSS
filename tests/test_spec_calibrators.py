import unittest

from mav_gss_lib.platform.spec.calibrators import (
    Calibrator,
    PolynomialCalibrator,
    PythonCalibrator,
)
from mav_gss_lib.platform.spec.calibrator_runtime import (
    CalibratorRuntime,
    PluginCallable,
)
from mav_gss_lib.platform.spec.errors import MissingPluginError
from mav_gss_lib.platform.spec.parameter_types import IntegerParameterType


class TestCalibrators(unittest.TestCase):
    def test_polynomial_dataclass_is_frozen(self):
        c = PolynomialCalibrator(coefficients=(0.0, 0.001), unit="V")
        with self.assertRaises(Exception):
            c.unit = "A"

    def test_polynomial_default_unit_is_empty_string(self):
        c = PolynomialCalibrator(coefficients=(1.0,))
        self.assertEqual(c.unit, "")

    def test_polynomial_coefficients_is_tuple(self):
        c = PolynomialCalibrator(coefficients=(0.0, 0.001))
        self.assertIsInstance(c.coefficients, tuple)

    def test_python_calibrator_carries_callable_ref_and_unit(self):
        c = PythonCalibrator(callable_ref="eps.compute_pwr", unit="W")
        self.assertEqual(c.callable_ref, "eps.compute_pwr")
        self.assertEqual(c.unit, "W")

    def test_calibrator_union_accepts_none(self):
        cal: Calibrator = None
        self.assertIsNone(cal)


class TestCalibratorRuntime(unittest.TestCase):
    def test_identity_when_calibrator_absent(self):
        types = {"V": IntegerParameterType(name="V", size_bits=16, signed=True, unit="raw")}
        rt = CalibratorRuntime(types=types, plugins={})
        self.assertEqual(rt.apply("V", 42), (42, "raw"))

    def test_polynomial_applies_coefficients_and_unit(self):
        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16, signed=True,
                calibrator=PolynomialCalibrator(coefficients=(0.0, 0.001), unit="V"),
            )
        }
        rt = CalibratorRuntime(types=types, plugins={})
        value, unit = rt.apply("V", 1500)
        self.assertAlmostEqual(value, 1.5, places=6)
        self.assertEqual(unit, "V")

    def test_python_calibrator_invokes_plugin(self):
        def double(raw):
            return (raw * 2, "x2")

        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16,
                calibrator=PythonCalibrator(callable_ref="m.double", unit="x2"),
            )
        }
        rt = CalibratorRuntime(types=types, plugins={"m.double": double})
        self.assertEqual(rt.apply("V", 21), (42, "x2"))

    def test_missing_plugin_raises_at_runtime_construction(self):
        types = {
            "V": IntegerParameterType(
                name="V", size_bits=16,
                calibrator=PythonCalibrator(callable_ref="m.missing"),
            )
        }
        with self.assertRaises(MissingPluginError):
            CalibratorRuntime(types=types, plugins={})


if __name__ == "__main__":
    unittest.main()
