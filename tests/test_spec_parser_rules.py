"""Tests for the seven missing parser graph-rule checks in yaml_parse.py.

Each TestCase covers exactly one rule, using a minimal invalid fixture that
violates only that rule. All tests assert that parse_yaml raises the
appropriate ParseError subclass.
"""

import unittest
from pathlib import Path

from mav_gss_lib.platform.spec.errors import InvalidDynamicRef, ParseError
from mav_gss_lib.platform.spec.yaml_parse import parse_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "spec"


class TestTypeCycle(unittest.TestCase):
    """Rule 1 — DFS through aggregate/array type_ref references detects cycles."""

    def test_aggregate_cycle_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_type_cycle.yml", plugins={})
        self.assertIn("cycle", str(ctx.exception).lower())


class TestParentArgsKeyMembership(unittest.TestCase):
    """Rule 2 — every parent_args key must be decoded by the parent container."""

    def test_unknown_parent_args_key_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_parent_args_key.yml", plugins={})
        self.assertIn("nonexistent_field", str(ctx.exception))


class TestEmptyPredicate(unittest.TestCase):
    """Rule 3 — a standalone non-abstract container with no packet predicates is rejected."""

    def test_no_restriction_criteria_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_empty_predicate.yml", plugins={})
        self.assertIn("no_pred", str(ctx.exception))


class TestRecursivePagedFrame(unittest.TestCase):
    """Rule 4 — a paged_frame_entry target may not itself contain a paged_frame_entry."""

    def test_nested_paged_frame_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_recursive_paged_frame.yml", plugins={})
        self.assertIn("reg_base", str(ctx.exception))


class TestDynamicRefForwardRef(unittest.TestCase):
    """Rule 5 — dynamic_ref size_ref must be decoded before the binary entry."""

    def test_forward_dynamic_ref_rejected(self):
        with self.assertRaises(InvalidDynamicRef) as ctx:
            parse_yaml(FIXTURES / "invalid_dynamic_ref.yml", plugins={})
        self.assertIn("blob_len", str(ctx.exception))


class TestEmptyDomain(unittest.TestCase):
    """Rule 6 — every non-abstract SequenceContainer must declare a non-empty domain."""

    def test_empty_domain_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_empty_domain.yml", plugins={})
        self.assertIn("no_domain", str(ctx.exception))


class TestArgBoundType(unittest.TestCase):
    """Rule 7 — valid_range is only valid on numeric argument types."""

    def test_valid_range_on_string_type_rejected(self):
        with self.assertRaises(ParseError) as ctx:
            parse_yaml(FIXTURES / "invalid_arg_bound_type.yml", plugins={})
        self.assertIn("mode_str", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
