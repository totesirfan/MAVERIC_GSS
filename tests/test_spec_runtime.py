import unittest
from dataclasses import dataclass

from mav_gss_lib.platform.spec.argument_types import (
    BUILT_IN_ARGUMENT_TYPES,
    StringArgumentType,
)
from mav_gss_lib.platform.spec.commands import Argument, MetaCommand
from mav_gss_lib.platform.spec.containers import (
    Comparison,
    ParameterRefEntry,
    RestrictionCriteria,
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
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker


@dataclass(frozen=True, slots=True)
class _Pkt:
    args_raw: bytes
    header: dict


def _mission(**overrides):
    types = dict(BUILT_IN_PARAMETER_TYPES)
    types["GncMode"] = EnumeratedParameterType(
        name="GncMode", size_bits=8,
        values=(EnumValue(raw=0, label="Safe"), EnumValue(raw=1, label="Auto")),
    )
    types["V_volts"] = IntegerParameterType(name="V_volts", size_bits=16, signed=True, unit="V")
    params = {
        "GNC_MODE": Parameter(name="GNC_MODE", type_ref="GncMode"),
        "V_BUS": Parameter(name="V_BUS", type_ref="V_volts"),
    }
    containers = {
        "gnc_get_mode_res": SequenceContainer(
            name="gnc_get_mode_res",
            entry_list=(ParameterRefEntry(name="GNC_MODE", type_ref="GncMode", parameter_ref="GNC_MODE"),),
            restriction_criteria=RestrictionCriteria(
                packet=(Comparison("cmd_id", "gnc_get_mode"), Comparison("ptype", "RES")),
            ),
            domain="gnc",
        ),
    }
    cmds = {
        "gnc_get_mode": MetaCommand(
            id="gnc_get_mode",
            packet={"dest": "LPPM", "echo": "NONE", "ptype": "CMD"},
        ),
        "set_v": MetaCommand(
            id="set_v",
            packet={"dest": "EPS", "echo": "NONE", "ptype": "CMD"},
            argument_list=(Argument(name="v", type_ref="u32"),),
        ),
    }
    return Mission(
        id="testmission", name="Test", header=MissionHeader(version="1.0.0", date="2026-04-25"),
        parameter_types=types,
        argument_types=dict(BUILT_IN_ARGUMENT_TYPES),
        parameters=params, bitfield_types={},
        sequence_containers=containers, meta_commands=cmds,
    )


class TestDeclarativeWalker(unittest.TestCase):
    def test_extract_emits_fragment_for_matching_packet(self):
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        pkt = _Pkt(args_raw=b"1", header={"cmd_id": "gnc_get_mode", "ptype": "RES"})
        updates = list(walker.extract(pkt, now_ms=42))
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].name, "gnc.GNC_MODE")
        self.assertEqual(updates[0].value, 1)

    def test_extract_no_match_yields_nothing(self):
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        pkt = _Pkt(args_raw=b"", header={"cmd_id": "missing", "ptype": "RES"})
        self.assertEqual(list(walker.extract(pkt, now_ms=0)), [])

    def test_encode_args_ascii_int(self):
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        out = walker.encode_args("set_v", {"v": 42})
        self.assertEqual(out, b"42")

    def test_encode_args_no_arguments_returns_empty(self):
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        out = walker.encode_args("gnc_get_mode", {})
        self.assertEqual(out, b"")

    def test_arg_run_size_returns_none_when_dynamic(self):
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        # u32 ASCII width is dynamic — return None
        self.assertIsNone(walker.arg_run_size("set_v"))

    def test_arg_run_size_with_two_string_args_returns_none(self):
        """StringArgumentType has no fixed-width encoding (only ascii_token /
        to_end), so any command with string args reports dynamic size."""
        from mav_gss_lib.platform.spec.commands import Argument, MetaCommand
        from mav_gss_lib.platform.spec.containers import SequenceContainer
        from mav_gss_lib.platform.spec.mission import Mission, MissionHeader
        from mav_gss_lib.platform.spec.parameter_types import (
            BUILT_IN_PARAMETER_TYPES,
        )
        types = dict(BUILT_IN_PARAMETER_TYPES)
        arg_types = dict(BUILT_IN_ARGUMENT_TYPES)
        arg_types["S_TOKEN"] = StringArgumentType(name="S_TOKEN", encoding="ascii_token")
        arg_types["S_END"] = StringArgumentType(name="S_END", encoding="to_end")
        cmds = {
            "two_strs": MetaCommand(
                id="two_strs",
                packet={"dest": "X", "echo": "NONE", "ptype": "CMD"},
                argument_list=(
                    Argument(name="a", type_ref="S_TOKEN"),
                    Argument(name="b", type_ref="S_END"),
                ),
            ),
        }
        m = Mission(
            id="m", name="m", header=MissionHeader(version="1.0.0", date="2026-04-25"),
            parameter_types=types,
            argument_types=arg_types,
            parameters={}, bitfield_types={},
            sequence_containers={}, meta_commands=cmds,
        )
        walker = DeclarativeWalker(m, plugins={})
        self.assertIsNone(walker.arg_run_size("two_strs"))

    def test_arg_run_size_no_args_returns_zero(self):
        """No arg list → 0 (no bytes, no separators)."""
        m = _mission()
        walker = DeclarativeWalker(m, plugins={})
        self.assertEqual(walker.arg_run_size("gnc_get_mode"), 0)


if __name__ == "__main__":
    unittest.main()
