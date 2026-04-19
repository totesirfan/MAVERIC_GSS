"""Grammar tests for MAVERIC cmd_line_to_payload.

Author:  Irfan Annuar - USC ISI SERC

Covers shortcut grammar, full grammar, and dispatcher selection. Locks
in the regression for F1: the first token must not be classified as a
shortcut unless it is an actual cmd_id in the schema — purely positional
heuristics (e.g. tokens[2] in {"NONE","TRUE","FALSE"}) would misfire on
full-grammar lines carrying ACK/NACK echoes.
"""
from __future__ import annotations

import unittest

from ops_test_support import CMD_DEFS, NODES

from mav_gss_lib.missions.maveric.tx_ops import (
    cmd_line_to_payload,
    parse_full_cli,
    parse_shortcut_cli,
)


class MaveericCliGrammar(unittest.TestCase):
    # gnc_get_mode has a fixed default dest in the schema, so the dispatcher
    # is free to treat it as a shortcut.
    SHORTCUT_CMD = "gnc_get_mode"

    def test_parse_shortcut_basic(self):
        payload = parse_shortcut_cli(self.SHORTCUT_CMD, CMD_DEFS, NODES)
        self.assertEqual(payload["cmd_id"], self.SHORTCUT_CMD)
        self.assertEqual(payload["args"], "")

    def test_parse_shortcut_with_args(self):
        payload = parse_shortcut_cli("gnc_set_mode 1", CMD_DEFS, NODES)
        self.assertEqual(payload["cmd_id"], "gnc_set_mode")
        self.assertEqual(payload["args"], "1")

    def test_dispatcher_picks_shortcut_when_head_in_schema(self):
        payload = cmd_line_to_payload(self.SHORTCUT_CMD, CMD_DEFS, NODES)
        self.assertEqual(payload["cmd_id"], self.SHORTCUT_CMD)

    def test_dispatcher_picks_full_when_head_not_in_schema(self):
        # First token is a node name, not a cmd_id — must be full grammar.
        payload = cmd_line_to_payload("GS LPPM NONE CMD com_ping", CMD_DEFS, NODES)
        self.assertEqual(payload["cmd_id"], "com_ping")

    def test_full_grammar_with_non_shortcut_head(self):
        # F1 regression: a heuristic checking positional tokens (e.g.
        # tokens[2] in {"NONE","TRUE","FALSE"}) would misclassify this line.
        # The schema-lookup dispatcher picks full grammar correctly because
        # "GS" is not a cmd_id in the schema.
        payload = cmd_line_to_payload("GS LPPM NONE CMD com_ping hello", CMD_DEFS, NODES)
        self.assertEqual(payload["cmd_id"], "com_ping")
        self.assertEqual(payload["args"], "hello")

    def test_empty_line_raises(self):
        with self.assertRaises(ValueError):
            cmd_line_to_payload("", CMD_DEFS, NODES)

    def test_shortcut_payload_carries_routing(self):
        payload = parse_shortcut_cli(self.SHORTCUT_CMD, CMD_DEFS, NODES)
        self.assertIn("dest", payload)
        self.assertIn("echo", payload)
        self.assertIn("ptype", payload)

    def test_full_parse_preserves_explicit_src(self):
        # When SRC is explicitly named (and differs from gs_node), it is
        # carried through as payload["src"].
        payload = parse_full_cli("LPPM EPS NONE CMD com_ping", NODES)
        self.assertIn("src", payload)


if __name__ == "__main__":
    unittest.main()
