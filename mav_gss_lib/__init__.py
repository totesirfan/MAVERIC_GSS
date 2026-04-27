"""mav_gss_lib — Ground Station Platform Library.

Mission-agnostic platform for CubeSat ground station software. The
FastAPI server in `server/` is the primary operational backend; it is
launched by `MAV_WEB.py` at the repo root. The React SPA in `web/` is
the operator dashboard.

Layout:

    platform/    — mission/platform boundary (contract/, rx/, tx/, config/,
                   framing/) + PlatformRuntime + loader
    missions/    — concrete missions (maveric + echo_v2 + balloon_v2)
    server/      — FastAPI backend (app, ws/, rx/, tx/, api/)
    web/         — React + Vite frontend (src/ + committed dist/)

    logging/     — session logging (SessionLog for RX, TXLog for TX)
    updater/     — self-updater + pre-import dependency bootstrap
    config.py    — split-state operator-config loader
    transport.py — ZMQ + PMT PDU helpers
    preflight.py — preflight check runner
    identity.py  — operator/host/station capture
    constants.py, textutil.py — small shared helpers

Module-naming convention:
    name.py     — public to the package (importable by siblings or external code)
    _name.py    — private helper (sibling-only); not part of the package's public surface

Examples of private helpers in this codebase: server/_atomics.py, server/_broadcast.py,
platform/_log_envelope.py, server/ws/_utils.py, logging/_base.py, updater/_helpers.py.
New private helpers should follow the underscore prefix.

Author: Irfan Annuar — USC ISI SERC
"""
