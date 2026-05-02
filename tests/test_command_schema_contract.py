"""/api/schema response shape contract.

Two layers:
  * Platform contract — runs in CI via the public fixture mission. Asserts
    the universal CommandSchemaItem shape (tx_args + UX flags only).
  * MAVERIC extension — local-only (skips when mission.yml absent).
    Asserts MAVERIC adds dest/echo/ptype/nodes and emits no other
    surprise keys.
"""

import unittest
from pathlib import Path

from mav_gss_lib.platform.contract.commands import (
    CommandSchemaItem,
    TxArgSchema,
)
from mav_gss_lib.platform.spec.command_codec import DeclarativeCommandOpsAdapter
from mav_gss_lib.platform.spec.runtime import DeclarativeWalker
from mav_gss_lib.platform.spec.yaml_parse import parse_yaml


_FIXTURE = Path("tests/fixtures/spec/argument_types_fixture_mission.yml")
_MISSION_YML = Path("mav_gss_lib/missions/maveric/mission.yml")


class _StubCodec:
    def complete_header(self, h): return h
    def wrap(self, h, b): return b


class _StubFramer:
    pass


class TestPlatformContractAgainstPublicFixture(unittest.TestCase):
    """Always-on CI check: platform CommandSchemaItem shape is honored
    by the platform-only DeclarativeCommandOpsAdapter (no mission
    wrapper).
    """

    @classmethod
    def setUpClass(cls):
        cls.mission = parse_yaml(_FIXTURE, plugins={})
        walker = DeclarativeWalker(cls.mission, plugins={})
        ops = DeclarativeCommandOpsAdapter(
            mission=cls.mission, walker=walker,
            packet_codec=_StubCodec(), framer=_StubFramer(),
        )
        cls.schema = ops.schema()

    def test_every_command_has_tx_args(self):
        for cmd_id, item in self.schema.items():
            self.assertIn("tx_args", item, f"{cmd_id} missing tx_args")
            self.assertIsInstance(item["tx_args"], list)

    def test_every_tx_arg_has_name_and_type(self):
        for cmd_id, item in self.schema.items():
            for arg in item.get("tx_args", []):
                self.assertIn("name", arg, f"{cmd_id}: arg missing name")
                self.assertIn("type", arg, f"{cmd_id}: arg missing type")

    def test_only_platform_keys_for_platform_adapter(self):
        # Platform adapter must NOT emit mission-specific keys
        # (dest/echo/ptype/nodes are MAVERIC's extension, not the
        # platform contract).
        allowed = set(CommandSchemaItem.__annotations__.keys())
        for cmd_id, item in self.schema.items():
            extras = set(item.keys()) - allowed
            self.assertFalse(
                extras,
                f"{cmd_id} platform adapter emitted extension keys "
                f"{extras}; those belong on a mission TypedDict, not on "
                f"the platform CommandSchemaItem.",
            )

    def test_arg_keys_are_in_TxArgSchema(self):
        allowed = set(TxArgSchema.__annotations__.keys())
        for cmd_id, item in self.schema.items():
            for arg in item.get("tx_args", []):
                extras = set(arg.keys()) - allowed
                self.assertFalse(
                    extras,
                    f"{cmd_id}.{arg.get('name')} returned unknown keys {extras}; "
                    f"add them to TxArgSchema TypedDict first",
                )


class TestFastApiEndpointDoesNotStripExtensionKeys(unittest.TestCase):
    """End-to-end check that mission-extension keys (dest/echo/ptype/
    nodes) survive FastAPI's serialization on /api/schema.

    Why this exists: tightening `api_schema`'s return annotation to
    `Mapping[str, CommandSchemaItem]` makes FastAPI try to coerce the
    response through a Pydantic model derived from the TypedDict —
    which would silently strip every key not declared on the platform
    contract (i.e. all of MAVERIC's routing fields). The route
    decorator's `response_model=None` opts out of that coercion. This
    test would FAIL if anyone ever drops `response_model=None` and
    catches the regression at HTTP boundary, not just at the
    `command_ops.schema()` call.
    """

    def test_extension_keys_round_trip_through_fastapi(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from mav_gss_lib.server.api.schema import router as schema_router

        # Stub runtime that returns a single command carrying both
        # platform fields AND MAVERIC-extension fields. We don't go
        # through the full WebRuntime here — the point is to prove
        # FastAPI doesn't strip keys, not to test runtime construction.
        class _StubMissionCommands:
            def schema(self):
                return {
                    "ppm_set_time": {
                        "tx_args": [{"name": "year", "type": "year_2digit_t"}],
                        "guard": False,
                        "rx_only": False,
                        "deprecated": False,
                        # MAVERIC extension — must survive serialization.
                        "dest": "LPPM",
                        "echo": "NONE",
                        "ptype": "CMD",
                        "nodes": ["LPPM", "UPPM"],
                    }
                }

        class _StubMission:
            commands = _StubMissionCommands()

        class _StubRuntime:
            mission = _StubMission()

        # `get_runtime(request)` walks `request.app.state.runtime`
        # (see mav_gss_lib/server/state.py::get_runtime). Setting
        # `app.state.runtime` is the entire wiring — no monkeypatch
        # needed. Earlier drafts also patched
        # `mav_gss_lib.server.state.get_runtime`, but the route module
        # imports `get_runtime` by name (`from ..state import get_runtime`)
        # so the rebound symbol lives on `mav_gss_lib.server.api.schema`
        # — patching the source module wouldn't change route lookup.
        # Drop the patch and rely on the supported `app.state.runtime`
        # contract instead.
        app = FastAPI()
        app.include_router(schema_router)
        app.state.runtime = _StubRuntime()

        client = TestClient(app)
        r = client.get("/api/schema")
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertIn("ppm_set_time", payload)
        item = payload["ppm_set_time"]
        # Every MAVERIC extension key must round-trip.
        for key in ("dest", "echo", "ptype", "nodes"):
            self.assertIn(
                key, item,
                f"FastAPI stripped MAVERIC extension key {key!r} from /api/schema; "
                f"check that the route decorator still has response_model=None.",
            )
        self.assertEqual(item["nodes"], ["LPPM", "UPPM"])
        # And platform fields still come through.
        self.assertEqual(item["tx_args"][0]["name"], "year")


@unittest.skipUnless(_MISSION_YML.exists(), "mission.yml is local-only; skip if absent")
class TestMavericExtensionAgainstLocalMission(unittest.TestCase):
    """Local-only deeper check: MAVERIC's wrapper emits the routing
    extension fields, and emits NO key outside the union of
    CommandSchemaItem ∪ MavericCommandSchemaItem.
    """

    @classmethod
    def setUpClass(cls):
        from mav_gss_lib.missions.maveric.declarative import build_declarative_capabilities
        from mav_gss_lib.missions.maveric.schema_types import MavericCommandSchemaItem
        caps = build_declarative_capabilities(
            mission_yml_path=str(_MISSION_YML),
            mission_cfg={"csp": {"prio": 2, "src": 0, "dest": 8, "dport": 24, "sport": 0, "flags": 0}},
        )
        cls.schema = caps.command_ops.schema()
        cls.maveric_keys = set(MavericCommandSchemaItem.__annotations__.keys())

    def test_at_least_one_command_carries_routing_fields(self):
        # ppm_set_time has allowed_dest=[LPPM, UPPM] — should populate `nodes`.
        item = self.schema["ppm_set_time"]
        self.assertIn("nodes", item)
        self.assertIn("LPPM", item["nodes"])

    def test_no_unknown_keys_outside_extension(self):
        for cmd_id, item in self.schema.items():
            extras = set(item.keys()) - self.maveric_keys
            self.assertFalse(
                extras,
                f"{cmd_id} returned keys {extras} not in "
                f"MavericCommandSchemaItem (which already includes the "
                f"platform CommandSchemaItem fields); add them to either "
                f"the platform contract OR MavericCommandSchemaItem first.",
            )


if __name__ == "__main__":
    unittest.main()
