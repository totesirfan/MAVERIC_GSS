"""MAVERIC command wire format.

`CommandFrame` is the single source of truth for MAVERIC's inner command
layout — both `build_cmd_raw()` (TX) and `try_parse_command()` (RX)
delegate to it. Outer CSP/AX.25/Golay framing lives in `framing.py`.

Inner layout:
    [src][dest][echo][ptype][id_len][args_len]
    [id_str][0x00][args_str][0x00][CRC-16 LE]

Wrapped CSP packet on the radio wire:
    [CSP v1 header 4B][command + CRC-16][CRC-32C 4B BE]  (csp_crc=true)
    [CSP v1 header 4B][command + CRC-16]                 (csp_crc=false)

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from typing import Any

from mav_gss_lib.protocols.crc import crc16


_CMD_HDR_LEN = 6  # src, dest, echo, ptype, id_len, args_len

class CommandFrame:
    """Symmetric encode/decode for the MAVERIC command wire format."""
    __slots__ = ("src", "dest", "echo", "pkt_type", "cmd_id", "args_str",
                 "args_raw", "crc", "crc_valid", "csp_crc32")

    def __init__(
        self,
        src: int,
        dest: int,
        echo: int,
        pkt_type: int,
        cmd_id: str,
        args_str: str = "",
        args_raw: bytes = b"",
        crc: int | None = None,
        crc_valid: bool | None = None,
        csp_crc32: int | None = None,
    ) -> None:
        self.src = src
        self.dest = dest
        self.echo = echo
        self.pkt_type = pkt_type
        self.cmd_id = cmd_id
        self.args_str = args_str
        self.args_raw = args_raw
        self.crc = crc
        self.crc_valid = crc_valid
        self.csp_crc32 = csp_crc32

    def to_bytes(self) -> bytearray:
        """Encode to raw wire bytes including CRC-16."""
        header = bytes([self.src & 0xFF, self.dest & 0xFF,
                        self.echo & 0xFF, self.pkt_type & 0xFF,
                        len(self.cmd_id) & 0xFF, len(self.args_str) & 0xFF])
        packet = bytearray(header)
        packet.extend(self.cmd_id.encode('ascii'))
        packet.append(0x00)
        packet.extend(self.args_str.encode('ascii'))
        packet.append(0x00)
        crc_val = crc16(packet)
        packet.extend(crc_val.to_bytes(2, byteorder='little'))
        return packet

    @classmethod
    def from_bytes(cls, payload: bytes) -> tuple["CommandFrame | None", bytes | None]:
        """Decode wire bytes into (CommandFrame, tail) or (None, None)."""
        if len(payload) < _CMD_HDR_LEN:
            return None, None

        src, dest, echo, pkt_type = payload[0], payload[1], payload[2], payload[3]
        id_len, args_len = payload[4], payload[5]

        if _CMD_HDR_LEN + id_len + 1 + args_len + 1 > len(payload):
            return None, None

        id_start = _CMD_HDR_LEN
        cmd_id = payload[id_start:id_start + id_len].decode("ascii", errors="replace").lower()

        null_pos = id_start + id_len
        if null_pos < len(payload) and payload[null_pos] == 0x00:
            null_pos += 1

        args_end = null_pos + args_len
        args_raw = bytes(payload[null_pos:args_end])
        args_str = args_raw.decode("ascii", errors="replace").strip()

        tail_start = args_end
        if tail_start < len(payload) and payload[tail_start] == 0x00:
            tail_start += 1

        # CRC-16 XMODEM (command integrity)
        crc_val = None
        crc_valid = None
        if tail_start + 2 <= len(payload):
            crc_val = payload[tail_start] | (payload[tail_start + 1] << 8)
            crc_valid = crc_val == crc16(payload[:tail_start])
            tail_start += 2
        else:
            crc_valid = False

        # CRC-32C (CSP packet integrity)
        csp_crc32 = None
        tail = payload[tail_start:]
        if len(tail) == 4:
            csp_crc32 = int.from_bytes(tail, 'big')
            tail = b""

        frame = cls(src, dest, echo, pkt_type, cmd_id, args_str,
                    args_raw, crc_val, crc_valid, csp_crc32)
        return frame, tail

    def to_dict(self) -> dict[str, Any]:
        """Convert to the parse-output dict shape consumed by `rx_ops`."""
        d = {
            "src": self.src, "dest": self.dest, "echo": self.echo,
            "pkt_type": self.pkt_type, "cmd_id": self.cmd_id,
            "args": self.args_str.split(), "crc": self.crc,
            "crc_valid": self.crc_valid, "csp_crc32": self.csp_crc32,
        }
        if self.args_raw:
            d["args_raw"] = self.args_raw
        return d


def build_cmd_raw(
    src: int,
    dest: int,
    cmd: str,
    args: str = "",
    echo: int = 0,
    ptype: int = 1,
) -> bytearray:
    """Build the raw inner MAVERIC command payload (with CRC-16).

    Caller passes `src` explicitly — the framer does not default it.
    Returns the bytearray ready for CSP wrapping by `framing.py`.
    """
    return CommandFrame(src, dest, echo, ptype, cmd, args).to_bytes()


def try_parse_command(payload: bytes) -> tuple[dict[str, Any] | None, bytes | None]:
    """Attempt to parse a byte payload as a MAVERIC command structure.

    Returns (parsed_dict, remaining_bytes) or (None, None) on failure.
    Uses CommandFrame.from_bytes() internally.
    """
    frame, tail = CommandFrame.from_bytes(payload)
    if frame is None:
        return None, None
    return frame.to_dict(), tail
