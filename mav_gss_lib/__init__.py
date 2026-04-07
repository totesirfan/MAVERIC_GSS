"""
mav_gss_lib -- Ground Station Platform Library

Mission-agnostic platform for CubeSat ground station software.
The web runtime (MAV_WEB.py) is the primary operational interface.

Core modules:
    mission_adapter  -- Mission boundary Protocol and shared loader
    protocols/       -- Protocol-family support (CRC, CSP, AX.25, KISS)
    parsing          -- RX packet processing pipeline
    logging          -- Session logging (JSONL + text)
    config           -- Shared config loader
    transport        -- ZMQ + PMT pub/sub
    web_runtime/     -- FastAPI web backend

Mission packages:
    missions/maveric/  -- MAVERIC CubeSat mission implementation

Author:  Irfan Annuar - USC ISI SERC
"""
