"""
mav_gss_lib.identity -- Operator & Station Identity Capture

Captures the OS-level operator, the hostname, and a display-label
station ID. Used by WebRuntime at startup and threaded through every
log record, session event, and preflight row.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

import getpass
import os
import socket


def capture_operator() -> str:
    """Return the real human OS account.

    Prefers SUDO_USER when GSS is launched with sudo (otherwise
    getpass.getuser() reports 'root'). Safe on headless Ubuntu where
    os.getlogin() can fail without a controlling TTY.
    """
    return os.getenv("SUDO_USER") or getpass.getuser()


def capture_host() -> str:
    """Return the machine hostname."""
    return socket.gethostname()


def capture_station(cfg: dict, host: str) -> str:
    """Return the display-label station ID.

    Looks up the hostname in the cfg `stations` catalog (top-level dict
    shared across all laptops). If the hostname isn't catalogued, falls
    back to the raw hostname as the display label — preserves readable
    output on any laptop whose entry hasn't been added yet.
    """
    stations = cfg.get("stations") or {}
    mapped = stations.get(host) or ""
    return mapped.strip() or host
