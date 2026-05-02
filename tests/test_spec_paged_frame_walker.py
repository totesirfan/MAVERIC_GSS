"""End-to-end coverage for paged_frame_entry walking.

Exercises the marker-bounded cursor path in EntryDecoder._walk_paged
against an ASCII-tokens parent container with `module,register` markers
and concrete child registers selected via parent_args.

Two scenarios that previously corrupted decoding:

  1. Q1 (FSS0_PDSUM register 33): a register whose payload is a single
     u32 token. The earlier `vec2_u16` declaration would consume the
     next register's marker as the second u16 element. With `u32` the
     marker boundary is honored.

  2. Q2 (blank registers `1,78 1,133 1,139`): a marker is followed by
     another marker with no payload tokens between them. Without the
     wrapper, the child container's decoder would steal the next
     register's marker token as numeric data, cascading corruption
     through every subsequent register.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from mav_gss_lib.platform.spec.argument_types import BUILT_IN_ARGUMENT_TYPES
from mav_gss_lib.platform.spec.containers import (
    Comparison,
    PagedFrameEntry,
    ParameterRefEntry,
    RestrictionCriteria,
    SequenceContainer,
)
from mav_gss_lib.platform.spec.mission import Mission, MissionHeader
from mav_gss_lib.platform.spec.parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    ArrayParameterType,
)
from mav_gss_lib.platform.spec.parameters import Parameter
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker


@dataclass(frozen=True, slots=True)
class _StubPacket:
    args_raw: bytes
    header: dict


def _build_walker() -> DeclarativeWalker:
    """Mission with a paged-frame parent and three child registers:
        - reg 33: u32           (PDSUM-style — one token)
        - reg 78: f32 vec3      (MTQ-style — three tokens)
        - reg 133: f32 vec3     (CAL_MAG_B-style)
    """
    types = dict(BUILT_IN_PARAMETER_TYPES)
    types["vec3_f32"] = ArrayParameterType(
        name="vec3_f32", array_type_ref="f32_le", dimension_list=(3,),
    )

    parameters = {
        "PDSUM": Parameter(name="PDSUM", type_ref="u32", domain="reg"),
        "MTQ": Parameter(name="MTQ", type_ref="vec3_f32", domain="reg"),
        "CAL_MAG_B": Parameter(name="CAL_MAG_B", type_ref="vec3_f32", domain="reg"),
    }

    # Abstract parent mirrors mtq_get_1_res: matches single-register packets
    # (cmd_id="single_pkt") and consumes module+register tokens to drive
    # child dispatch via parent_args. Children inherit from this abstract
    # parent regardless of which packet (single or paged) carries them.
    parent = SequenceContainer(
        name="paged_parent",
        layout="ascii_tokens",
        abstract=True,
        restriction_criteria=RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="single_pkt"),),
        ),
        entry_list=(
            ParameterRefEntry(name="module", type_ref="u8", emit=False),
            ParameterRefEntry(name="register", type_ref="u8", emit=False),
        ),
    )
    page_carrier = SequenceContainer(
        name="page_carrier",
        layout="ascii_tokens",
        restriction_criteria=RestrictionCriteria(
            packet=(Comparison(parameter_ref="cmd_id", value="paged_pkt"),),
        ),
        entry_list=(
            PagedFrameEntry(
                base_container_ref="paged_parent",
                marker_separator=",",
                dispatch_keys=("module", "register"),
                on_unknown_register="skip",
            ),
        ),
    )
    reg_pdsum = SequenceContainer(
        name="reg_PDSUM",
        layout="ascii_tokens",
        base_container_ref="paged_parent",
        restriction_criteria=RestrictionCriteria(
            parent_args=(
                Comparison(parameter_ref="module", value=1),
                Comparison(parameter_ref="register", value=33),
            ),
        ),
        entry_list=(ParameterRefEntry(name="PDSUM", type_ref="u32"),),
    )
    reg_mtq = SequenceContainer(
        name="reg_MTQ",
        layout="ascii_tokens",
        base_container_ref="paged_parent",
        restriction_criteria=RestrictionCriteria(
            parent_args=(
                Comparison(parameter_ref="module", value=1),
                Comparison(parameter_ref="register", value=78),
            ),
        ),
        entry_list=(ParameterRefEntry(name="MTQ", type_ref="vec3_f32"),),
    )
    reg_cal_mag = SequenceContainer(
        name="reg_CAL_MAG_B",
        layout="ascii_tokens",
        base_container_ref="paged_parent",
        restriction_criteria=RestrictionCriteria(
            parent_args=(
                Comparison(parameter_ref="module", value=1),
                Comparison(parameter_ref="register", value=133),
            ),
        ),
        entry_list=(ParameterRefEntry(name="CAL_MAG_B", type_ref="vec3_f32"),),
    )

    mission = Mission(
        id="t",
        name="t",
        header=MissionHeader(version="0", date="2026-01-01"),
        parameter_types=types,
        argument_types=dict(BUILT_IN_ARGUMENT_TYPES),
        parameters=parameters,
        bitfield_types={},
        sequence_containers={
            parent.name: parent,
            page_carrier.name: page_carrier,
            reg_pdsum.name: reg_pdsum,
            reg_mtq.name: reg_mtq,
            reg_cal_mag.name: reg_cal_mag,
        },
        meta_commands={},
    )
    return DeclarativeWalker(mission, plugins={})


def _names(updates) -> list[str]:
    return [u.name for u in updates]


class TestPagedFramePdsumSingleToken(unittest.TestCase):
    """Q1: register 33 (PDSUM) carries one u32 token; the next marker
    must remain unconsumed for the outer paged loop.
    """

    def test_single_token_register_does_not_steal_next_marker(self):
        walker = _build_walker()
        # PDSUM = 0, then MTQ marker + 3 floats
        pkt = _StubPacket(
            args_raw=b"1,33 0 1,78 1.0 2.0 3.0",
            header={"cmd_id": "paged_pkt"},
        )
        updates = list(walker.extract(pkt, now_ms=0))
        names = _names(updates)
        self.assertIn("reg.PDSUM", names)
        self.assertIn("reg.MTQ", names)
        pdsum = next(u for u in updates if u.name == "reg.PDSUM")
        mtq = next(u for u in updates if u.name == "reg.MTQ")
        self.assertEqual(pdsum.value, 0)
        self.assertEqual(mtq.value, [1.0, 2.0, 3.0])


class TestPagedFrameUnderSuppliedPayload(unittest.TestCase):
    """Q2: a marker followed immediately by another marker (no payload
    between them) must skip the under-supplied register and decode the
    rest, not steal the trailing markers as numeric data.
    """

    def test_blank_register_skips_and_following_register_still_decodes(self):
        walker = _build_walker()
        # MTQ (78) with no payload, then CAL_MAG_B (133) with 3 floats
        pkt = _StubPacket(
            args_raw=b"1,78 1,133 4.0 5.0 6.0",
            header={"cmd_id": "paged_pkt"},
        )
        updates = list(walker.extract(pkt, now_ms=0))
        names = _names(updates)
        self.assertNotIn("reg.MTQ", names)
        self.assertIn("reg.CAL_MAG_B", names)
        cal = next(u for u in updates if u.name == "reg.CAL_MAG_B")
        self.assertEqual(cal.value, [4.0, 5.0, 6.0])

    def test_three_consecutive_blank_register_markers_yield_nothing(self):
        walker = _build_walker()
        # All three markers, no payloads at all.
        pkt = _StubPacket(
            args_raw=b"1,33 1,78 1,133",
            header={"cmd_id": "paged_pkt"},
        )
        updates = list(walker.extract(pkt, now_ms=0))
        # No register has its payload, so no parameters are emitted, but
        # decoding completes without raising and consumes every marker.
        self.assertEqual(updates, [])

    def test_partial_payload_for_first_register_then_next_marker(self):
        walker = _build_walker()
        # MTQ (78) gets only 2 of 3 expected tokens; next is CAL_MAG_B
        # marker. MTQ must skip cleanly; CAL_MAG_B must decode its 3.
        pkt = _StubPacket(
            args_raw=b"1,78 1.0 2.0 1,133 4.0 5.0 6.0",
            header={"cmd_id": "paged_pkt"},
        )
        updates = list(walker.extract(pkt, now_ms=0))
        names = _names(updates)
        self.assertNotIn("reg.MTQ", names)
        self.assertIn("reg.CAL_MAG_B", names)


if __name__ == "__main__":
    unittest.main()
