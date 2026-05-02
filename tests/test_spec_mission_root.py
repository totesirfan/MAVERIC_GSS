import unittest

from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
from mav_gss_lib.platform.spec.commands import MetaCommand
from mav_gss_lib.platform.spec.containers import SequenceContainer
from mav_gss_lib.platform.spec.mission import (
    ContainerShadow,
    Mission,
    MissionHeader,
    ParseWarning,
)
from mav_gss_lib.platform.spec.parameters import Parameter
from mav_gss_lib.platform.spec.parameter_types import IntegerParameterType


class TestMissionRoot(unittest.TestCase):
    def setUp(self):
        self.header = MissionHeader(version="1.0.0", date="2026-04-25")
        self.types = {"V_volts": IntegerParameterType(name="V_volts", size_bits=16, signed=True)}
        self.params = {"V_BUS": Parameter(name="V_BUS", type_ref="V_volts")}
        self.containers = {
            "eps_hk": SequenceContainer(name="eps_hk", entry_list=(), domain="eps"),
            "gnc_get_mode_res": SequenceContainer(name="gnc_get_mode_res", entry_list=(), domain="gnc"),
        }
        self.cmds = {"eps_hk": MetaCommand(id="eps_hk")}

    def test_mission_holds_typed_maps(self):
        m = Mission(
            id="maveric", name="MAVERIC CubeSat", header=self.header,
            parameter_types=self.types,
            argument_types=dict(BUILT_IN_ARGUMENT_TYPES),
            parameters=self.params,
            bitfield_types={}, sequence_containers=self.containers,
            meta_commands=self.cmds,
        )
        self.assertEqual(m.id, "maveric")
        self.assertIs(m.parameter_types["V_volts"], self.types["V_volts"])

    def test_parse_warnings_default_empty(self):
        m = Mission(
            id="maveric", name="MAVERIC CubeSat", header=self.header,
            parameter_types={},
            argument_types=dict(BUILT_IN_ARGUMENT_TYPES),
            parameters={},
            bitfield_types={}, sequence_containers={},
            meta_commands={},
        )
        self.assertEqual(m.parse_warnings, ())

    def test_container_shadow_warning_carries_pair(self):
        w = ContainerShadow(broader="A", specific="B")
        self.assertEqual(w.broader, "A")
        self.assertEqual(w.specific, "B")
        self.assertIn("A", str(w))
        self.assertIn("B", str(w))
        self.assertIsInstance(w, ParseWarning)


if __name__ == "__main__":
    unittest.main()
