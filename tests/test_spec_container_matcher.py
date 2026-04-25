import unittest
from dataclasses import dataclass

from mav_gss_lib.platform.spec.containers import (
    Comparison,
    RestrictionCriteria,
    SequenceContainer,
)
from mav_gss_lib.platform.spec.runtime import ContainerMatcher


@dataclass(frozen=True, slots=True)
class _Pkt:
    args_raw: bytes
    header: dict


def _container(name: str, *, packet=(), parent_args=(), base_container_ref=None,
               abstract=False, domain="d") -> SequenceContainer:
    return SequenceContainer(
        name=name,
        entry_list=(),
        restriction_criteria=RestrictionCriteria(packet=packet, parent_args=parent_args),
        base_container_ref=base_container_ref,
        abstract=abstract,
        domain=domain,
    )


class TestMatchParent(unittest.TestCase):
    def test_match_parent_returns_first_satisfying_container(self):
        a = _container("a", packet=(Comparison("cmd_id", "x"),))
        b = _container("b", packet=(Comparison("cmd_id", "y"),))
        m = ContainerMatcher(containers={"a": a, "b": b})
        pkt = _Pkt(args_raw=b"", header={"cmd_id": "y"})
        self.assertIs(m.match_parent(pkt), b)

    def test_match_parent_skips_concrete_children(self):
        parent = _container("p", packet=(Comparison("cmd_id", "x"),))
        child = _container("c", parent_args=(Comparison("module", 1),), base_container_ref="p")
        m = ContainerMatcher(containers={"p": parent, "c": child})
        pkt = _Pkt(args_raw=b"", header={"cmd_id": "x"})
        self.assertIs(m.match_parent(pkt), parent)

    def test_match_parent_returns_none_on_no_match(self):
        a = _container("a", packet=(Comparison("cmd_id", "x"),))
        m = ContainerMatcher(containers={"a": a})
        pkt = _Pkt(args_raw=b"", header={"cmd_id": "missing"})
        self.assertIsNone(m.match_parent(pkt))


class TestResolveConcrete(unittest.TestCase):
    def test_resolve_concrete_matches_first_satisfying_child(self):
        parent = _container("p", packet=(Comparison("cmd_id", "x"),))
        c1 = _container("c1", parent_args=(Comparison("module", 1),), base_container_ref="p")
        c2 = _container("c2", parent_args=(Comparison("module", 2),), base_container_ref="p")
        m = ContainerMatcher(containers={"p": parent, "c1": c1, "c2": c2})
        self.assertIs(m.resolve_concrete("p", {"module": 2}), c2)

    def test_resolve_concrete_returns_none_when_no_match(self):
        parent = _container("p", packet=(Comparison("cmd_id", "x"),))
        c1 = _container("c1", parent_args=(Comparison("module", 1),), base_container_ref="p")
        m = ContainerMatcher(containers={"p": parent, "c1": c1})
        self.assertIsNone(m.resolve_concrete("p", {"module": 99}))

    def test_has_concrete_children(self):
        parent = _container("p", packet=(Comparison("cmd_id", "x"),))
        c1 = _container("c1", parent_args=(Comparison("module", 1),), base_container_ref="p")
        m = ContainerMatcher(containers={"p": parent, "c1": c1})
        self.assertTrue(m.has_concrete_children("p"))
        self.assertFalse(m.has_concrete_children("c1"))


if __name__ == "__main__":
    unittest.main()
