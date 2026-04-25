import unittest

from mav_gss_lib.platform.spec.bitfield import BitfieldEntry, BitfieldType
from mav_gss_lib.platform.spec.calibrators import PolynomialCalibrator
from mav_gss_lib.platform.spec.catalog import CatalogBuilder
from mav_gss_lib.platform.spec.containers import (
    ParameterRefEntry,
    SequenceContainer,
)
from mav_gss_lib.platform.spec.mission import Mission, MissionHeader
from mav_gss_lib.platform.spec.parameters import Parameter
from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    EnumeratedParameterType,
    EnumValue,
    IntegerParameterType,
)


def _mission():
    types = dict(BUILT_IN_PARAMETER_TYPES)
    types["V_volts"] = IntegerParameterType(
        name="V_volts", size_bits=16, signed=True,
        calibrator=PolynomialCalibrator(coefficients=(0.0, 0.001), unit="V"),
        valid_range=(-32.0, 32.0),
    )
    types["GncMode"] = EnumeratedParameterType(
        name="GncMode", size_bits=8,
        values=(EnumValue(raw=0, label="Safe"), EnumValue(raw=1, label="Auto")),
    )
    bfs = {
        "STAT_REG": BitfieldType(
            name="STAT_REG", size_bits=8,
            entry_list=(
                BitfieldEntry(name="thr_ok", bits=(0, 0), kind="bool"),
                BitfieldEntry(name="mode", bits=(1, 2), kind="enum", enum_ref="GncMode"),
            ),
        ),
    }
    params = {
        "V_BUS": Parameter(name="V_BUS", type_ref="V_volts", description="Unregulated bus"),
        "GNC_MODE": Parameter(name="GNC_MODE", type_ref="GncMode", description="Planner mode"),
        "STAT": Parameter(name="STAT", type_ref="STAT_REG", description="Status register"),
    }
    containers = {
        "eps_hk": SequenceContainer(
            name="eps_hk", domain="eps", layout="binary",
            entry_list=(ParameterRefEntry(name="V_BUS", type_ref="V_volts", parameter_ref="V_BUS"),),
        ),
        "gnc_get_mode_res": SequenceContainer(
            name="gnc_get_mode_res", domain="gnc",
            entry_list=(
                ParameterRefEntry(name="GNC_MODE", type_ref="GncMode", parameter_ref="GNC_MODE"),
                ParameterRefEntry(name="STAT", type_ref="STAT_REG", parameter_ref="STAT"),
            ),
        ),
    }
    return Mission(
        id="m", name="m", header=MissionHeader(version="1.0.0", date="2026-04-25"),
        parameter_types=types, parameters=params, bitfield_types=bfs,
        sequence_containers=containers, meta_commands={},
    )


class TestCatalogBuilder(unittest.TestCase):
    def test_eps_domain_carries_v_bus_with_calibrator_unit(self):
        cb = CatalogBuilder(_mission())
        cat = cb.for_domain("eps")
        self.assertIn("V_BUS", cat["params"])
        self.assertEqual(cat["params"]["V_BUS"]["unit"], "V")
        self.assertEqual(cat["params"]["V_BUS"]["description"], "Unregulated bus")
        self.assertEqual(cat["params"]["V_BUS"]["valid_range"], [-32.0, 32.0])

    def test_gnc_domain_carries_enum_labels(self):
        cb = CatalogBuilder(_mission())
        cat = cb.for_domain("gnc")
        self.assertEqual(
            cat["params"]["GNC_MODE"]["enum_labels"],
            {"0": "Safe", "1": "Auto"},
        )

    def test_bitfield_metadata_projected(self):
        cb = CatalogBuilder(_mission())
        cat = cb.for_domain("gnc")
        bf = cat["params"]["STAT"]["bitfield"]
        self.assertEqual(bf["thr_ok"]["bits"], [0, 0])
        self.assertEqual(bf["mode"]["bits"], [1, 2])
        self.assertEqual(bf["mode"]["enum_labels"], {"0": "Safe", "1": "Auto"})

    def test_unknown_domain_returns_empty_params(self):
        cb = CatalogBuilder(_mission())
        self.assertEqual(cb.for_domain("nonexistent"), {"params": {}})


if __name__ == "__main__":
    unittest.main()
