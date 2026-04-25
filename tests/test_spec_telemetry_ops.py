import unittest
from dataclasses import dataclass, field
from pathlib import Path

from mav_gss_lib.platform.contract.telemetry import TelemetryOps
from mav_gss_lib.platform.spec.telemetry_ops import (
    DeclarativeWalkerExtractor,
    build_declarative_telemetry_ops,
)
from mav_gss_lib.platform.spec.yaml_parse import parse_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "spec" / "minimal_mission.yml"


@dataclass(frozen=True, slots=True)
class _MaverPacket:
    args_raw: bytes
    header: dict


@dataclass
class _MissionPayload:
    maver_packet: object


@dataclass
class _PacketEnvelope:
    mission_payload: object
    received_at_ms: int = 0


class TestBuildTelemetryOps(unittest.TestCase):
    def test_returns_telemetry_ops_with_one_extractor(self):
        m = parse_yaml(FIXTURE, plugins={})
        ops = build_declarative_telemetry_ops(m, plugins={})
        self.assertIsInstance(ops, TelemetryOps)
        self.assertEqual(len(ops.extractors), 1)
        self.assertIsInstance(ops.extractors[0], DeclarativeWalkerExtractor)

    def test_one_domain_spec_per_declared_domain(self):
        m = parse_yaml(FIXTURE, plugins={})
        ops = build_declarative_telemetry_ops(m, plugins={})
        self.assertEqual(set(ops.domains), {"eps", "gnc"})

    def test_each_domain_spec_carries_catalog_callable(self):
        m = parse_yaml(FIXTURE, plugins={})
        ops = build_declarative_telemetry_ops(m, plugins={})
        cat = ops.domains["gnc"].catalog()
        self.assertIn("GNC_MODE", cat["params"])

    def test_extractor_reads_maver_packet_from_envelope(self):
        m = parse_yaml(FIXTURE, plugins={})
        ops = build_declarative_telemetry_ops(m, plugins={})
        ext = ops.extractors[0]
        packet = _PacketEnvelope(
            mission_payload=_MissionPayload(
                maver_packet=_MaverPacket(args_raw=b"1", header={"cmd_id": "gnc_get_mode", "ptype": "RES"}),
            ),
            received_at_ms=42,
        )
        fragments = list(ext.extract(packet))
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0].key, "GNC_MODE")


if __name__ == "__main__":
    unittest.main()
