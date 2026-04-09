#!/usr/bin/env python3
"""Preflight check for MAVERIC GSS startup prerequisites.

Run before launching MAV_WEB.py to verify the environment is ready.

Usage:
    python3 scripts/preflight.py
"""

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "mav_gss_lib"
OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"
errors = 0


def check(label, ok, fix=""):
    global errors
    if ok:
        print(f"  {OK} {label}")
    else:
        errors += 1
        print(f"  {FAIL} {label}")
        if fix:
            print(f"      → {fix}")


def warn(label, msg=""):
    print(f"  {WARN} {label}")
    if msg:
        print(f"      → {msg}")


print("\n── Python Dependencies ──")
for mod, pkg, install in [
    ("fastapi", "fastapi", "pip install fastapi"),
    ("uvicorn", "uvicorn", "pip install uvicorn"),
    ("websockets", "websockets", "pip install websockets"),
    ("yaml", "PyYAML", "pip install PyYAML"),
    ("zmq", "pyzmq", "pip install pyzmq"),
    ("crcmod", "crcmod", "pip install crcmod"),
]:
    try:
        importlib.import_module(mod)
        check(pkg, True)
    except ImportError:
        check(pkg, False, install)

print("\n── GNU Radio / PMT ──")
try:
    import pmt
    check("pmt (GNU Radio)", True)
except ImportError:
    check("pmt (GNU Radio)", False,
          "Activate radioconda environment: conda activate radioconda")

print("\n── Config Files ──")
gss_yml = LIB / "gss.yml"
gss_example = LIB / "gss.example.yml"
check("gss.yml exists", gss_yml.is_file(),
      f"Copy from example: cp {gss_example} {gss_yml}")

# Detect active mission from config
mission = "maveric"
cfg = {}
if gss_yml.is_file():
    try:
        import yaml
        with open(gss_yml) as f:
            cfg = yaml.safe_load(f) or {}
        mission = cfg.get("general", {}).get("mission", "maveric")
    except Exception:
        pass

mission_dir = LIB / "missions" / mission
check(f"Mission package exists: {mission}", mission_dir.is_dir(),
      f"Set general.mission in gss.yml or create {mission_dir}")

# Resolve command schema path (common mission-package path).
# Reads general.command_defs from config, checks mission package dir.
# Note: MAVERIC's init_mission has an additional fallback to config/
# that we don't replicate here — preflight checks the common path.
cmd_defs_name = "commands.yml"
if gss_yml.is_file():
    try:
        cmd_defs_name = cfg.get("general", {}).get("command_defs", "commands.yml")
    except Exception:
        pass

if os.path.isabs(cmd_defs_name):
    cmd_schema = Path(cmd_defs_name)
else:
    cmd_schema = mission_dir / cmd_defs_name

cmd_example = mission_dir / (Path(cmd_defs_name).stem + ".example" + Path(cmd_defs_name).suffix)
if cmd_schema.is_file():
    check(f"Command schema: {cmd_schema.name}", True)
elif cmd_example.is_file():
    warn(f"Command schema missing: {cmd_schema.name}",
         f"Copy from example: cp {cmd_example} {cmd_schema}")
else:
    warn(f"No command schema found: {cmd_schema}",
         "System starts but cannot validate or send commands")

print("\n── Web Build ──")
dist = LIB / "web" / "dist"
index = dist / "index.html"
check("Web build present (dist/index.html)", index.is_file(),
      "Run: cd mav_gss_lib/web && npm install && npm run build")

print("\n── ZMQ Addresses ──")
if gss_yml.is_file():
    try:
        rx_addr = cfg.get("rx", {}).get("zmq_addr", "tcp://127.0.0.1:52001")
        tx_addr = cfg.get("tx", {}).get("zmq_addr", "tcp://127.0.0.1:52002")
        print(f"  RX SUB: {rx_addr}")
        print(f"  TX PUB: {tx_addr}")
    except Exception:
        print("  (could not read ZMQ addresses from config)")
else:
    print("  RX SUB: tcp://127.0.0.1:52001 (default)")
    print("  TX PUB: tcp://127.0.0.1:52002 (default)")

print()
if errors:
    print(f"  {errors} issue(s) found. Fix before launching MAV_WEB.py.\n")
    sys.exit(1)
else:
    print(f"  All checks passed. Ready to run: python3 MAV_WEB.py\n")
