# Maintainer Handoff

> **This document has been retired.** It described the pre-platform adapter-era
> runtime. The current startup path uses `PlatformRuntime` and
> `MissionSpec`. Until a full rewrite lands, orient yourself from these
> sources instead:
>
> - **Entry point** — `MAV_WEB.py` bootstraps via `mav_gss_lib.updater.bootstrap_dependencies()`
>   then calls `mav_gss_lib.server.app.create_app()`.
> - **Runtime container** — `mav_gss_lib/server/state.py::WebRuntime`
>   owns split config (`platform_cfg`, `mission_id`, `mission_cfg`), the
>   `PlatformRuntime`, `MissionSpec`, RX/TX services, and session/update/preflight state.
> - **Platform API** — `mav_gss_lib/platform/` (capability contracts in
>   `contract/mission.py`, `contract/commands.py`, `contract/packets.py`,
>   `contract/rendering.py`, `contract/telemetry.py`, `contract/events.py`,
>   `contract/ui.py`, `contract/http.py`; RX pipeline in `rx/pipeline.py`
>   plus `rx/packets.py` / `rx/telemetry.py` / `rx/events.py` /
>   `rx/rendering.py` / `rx/logging.py`; TX pipeline in `tx/commands.py`
>   and `tx/logging.py`; `runtime.py::PlatformRuntime` is the production
>   constructor; `loader.py::load_mission_spec_from_split` loads the
>   active mission).
> - **Mission packages** — `mav_gss_lib/missions/<id>/mission.py::build(ctx)`
>   returns a `MissionSpec`. MAVERIC is the reference
>   (`mav_gss_lib/missions/maveric/`); `echo_v2` and `balloon_v2` are
>   fixture missions that exercise the boundary.
> - **Config** — operator file is `mav_gss_lib/gss.yml`
>   (platform section) + mission config under `mission.config` (MAVERIC
>   schema is `mav_gss_lib/missions/maveric/commands.yml`, gitignored).
>   `mav_gss_lib/config.py::load_split_config` returns
>   `(platform_cfg, mission_id, mission_cfg)`.
> - **Tests** — guardrail tests in `tests/test_runtime_split_state.py`,
>   `tests/test_platform_*.py` (architecture, config boundary/spec,
>   runtime, command/packet/render/telemetry/rx pipelines, logging,
>   mission specs), `tests/test_mission_owned_framing.py`, and
>   `tests/test_api_config_get_contract.py` enforce the platform
>   boundary invariants (no `runtime.cfg` reads, no
>   `mav_gss_lib.protocols.*` imports under `server/`, no `runtime.csp` /
>   `runtime.ax25` access, etc).
