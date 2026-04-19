"""Wire-byte golden hashes for build_cmd_raw.

Author:  Irfan Annuar - USC ISI SERC

Any refactor that claims to preserve wire bytes MUST pass this file both
before and after the change. Hashes are captured pre-refactor and
committed as a guard-rail.
"""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mav_gss_lib.missions.maveric.wire_format import build_cmd_raw


class BuildCmdRawWireBytes(unittest.TestCase):
    def _hash(self, **kwargs) -> str:
        return hashlib.sha256(bytes(build_cmd_raw(**kwargs))).hexdigest()

    def test_empty_args(self):
        h = self._hash(origin=6, dest=2, cmd="com_ping", args="", echo=0, ptype=1)
        self.assertEqual(h, "07edcc5a2cdcbc1ce988e45222ed10bed27a23225cf4341df119586252549404")

    def test_str_arg(self):
        h = self._hash(origin=6, dest=2, cmd="com_ping", args="hello", echo=0, ptype=1)
        self.assertEqual(h, "af3a6b98260b1512cc8cd4ac8bd1c8dcc119e8811bb203a97c987f0462639336")

    def test_multi_arg(self):
        h = self._hash(origin=6, dest=2, cmd="gnc_set_mode", args="NOMINAL 1", echo=0, ptype=1)
        self.assertEqual(h, "75f1b08e232d964f847ebc3b6b27bfab247fb9ec51dbd7f9df4d0ad38cdfdfcb")

    def test_epoch_ms_arg(self):
        h = self._hash(origin=6, dest=2, cmd="ppm_set_time", args="1700000000000", echo=0, ptype=1)
        self.assertEqual(h, "780eb0fb2847bbb8635fdcb9af316dd74960ba0ace80f330024bc8be0817c0ff")

    def test_high_ptype(self):
        h = self._hash(origin=6, dest=2, cmd="com_ping", args="", echo=1, ptype=7)
        self.assertEqual(h, "5aa66ab7cb400693060512c261fc134770763ac36d8691665ba33c5243cd371f")


if __name__ == "__main__":
    unittest.main()
