"""
mav_gss_lib.display -- Terminal Display Helpers

ANSI color theme, 80-column box drawing, and text formatting utilities
shared between MAV_RX and MAV_TX for consistent visual output.

Color theme is centralized in the Theme class -- change colors in one
place and both tools update. All display code references C.LABEL,
C.VALUE, etc. instead of raw ANSI codes.

Author:  Irfan Annuar - USC ISI SERC
"""

import re


# =============================================================================
#  COLOR THEME
#
#  All terminal colors are defined here. To retheme the entire GSS suite,
#  edit only this class. Every display function references C.<role> so
#  colors stay consistent across MAV_RX and MAV_TX.
#
#  Supports standard ANSI (16-color), 256-color, and 24-bit true color.
#  Examples:
#    Standard:   "\033[96m"                     (bright cyan)
#    256-color:  "\033[38;5;208m"               (orange)
#    True color: "\033[38;2;153;0;0m"           (USC Cardinal)
# =============================================================================

class Theme:
    """Centralized color definitions for the MAVERIC GSS terminal UI."""

    # -- Semantic roles (what it means, not what color it is) --
    LABEL    = "\033[96m"    # field labels: CSP V1, CMD, SAT TIME, HEX
    VALUE    = "\033[1m"     # field values: node IDs, command names, args
    SUCCESS  = "\033[92m"    # TX/RX success: packet received, command sent
    WARNING  = "\033[93m"    # warnings: AX.25 frames, batch mode, silence
    ERROR    = "\033[91m"    # errors: unknown frames, parse failures
    DIM      = "\033[2m"     # secondary info: borders, timestamps, metadata
    BOLD     = "\033[1m"     # emphasis (alias for VALUE, used in banners)
    END      = "\033[0m"     # reset all attributes

    # -- Frame type colors (RX only) --
    AX25     = "\033[93m"    # AX.25 frame indicator
    AX100    = "\033[92m"    # AX100 frame indicator
    UNKNOWN  = "\033[91m"    # unknown frame type

    @classmethod
    def frame_color(cls, frame_type):
        """Return the color for a given frame type string."""
        return {
            "AX.25":   cls.AX25,
            "AX100":   cls.AX100,
        }.get(frame_type, cls.UNKNOWN)


# Module-level alias for convenience: C.LABEL, C.VALUE, etc.
C = Theme


# =============================================================================
#  BOX DRAWING
# =============================================================================

BOX_W = 80
INN_W = BOX_W - 4

TOP = f"\u250c{'\u2500' * (BOX_W - 2)}\u2510"
MID = f"\u251c{'\u2500' * (BOX_W - 2)}\u2524"
BOT = f"\u2514{'\u2500' * (BOX_W - 2)}\u2518"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s):
    """Remove ANSI escape codes, return visible text only."""
    return _ANSI_RE.sub("", s)


def row(content=""):
    """Format one box row with dim borders, padded to align right border."""
    visible_len = len(strip_ansi(content))
    pad = max(0, INN_W - visible_len)
    return f"{C.DIM}\u2502{C.END} {content}{' ' * pad} {C.DIM}\u2502{C.END}"


# =============================================================================
#  TEXT HELPERS
# =============================================================================

ASCII_LINE_W = INN_W - 14  # "  ASCII       " prefix = 14 visible chars


def wrap_ascii(payload):
    """Convert payload bytes to printable ASCII, wrapped to fit inside box.
    Returns list of pre-formatted row strings."""
    text = ''.join(chr(b) if 32 <= b < 127 else '\u00b7' for b in payload)
    lines = []
    for i in range(0, len(text), ASCII_LINE_W):
        chunk = text[i:i + ASCII_LINE_W]
        if i == 0:
            lines.append(row(f"  {C.DIM}ASCII{C.END}       {C.DIM}{chunk}{C.END}"))
        else:
            lines.append(row(f"              {C.DIM}{chunk}{C.END}"))
    return lines


def wrap_hex(hex_str, bytes_per_line=20):
    """Wrap a hex string into multiple rows with HEX label on first line.
    Returns list of pre-formatted row strings."""
    parts = hex_str.split(" ")
    lines = []
    for i in range(0, len(parts), bytes_per_line):
        chunk = " ".join(parts[i:i + bytes_per_line])
        if i == 0:
            lines.append(row(f"  {C.SUCCESS}HEX{C.END}         {chunk}"))
        else:
            lines.append(row(f"              {chunk}"))
    return lines


# =============================================================================
#  BANNER & INFO
# =============================================================================

def banner(title, version):
    """Print a centered banner box for application startup."""
    w = 58
    border = '\u2500' * w
    print(f"\n{C.BOLD}\u250c{border}\u2510")
    print(f"\u2502{C.END}{C.BOLD}{title.center(w)}{C.END}{C.BOLD}\u2502")
    print(f"\u2502{C.END}{C.DIM}{'v' + version:^{w}}{C.END}{C.BOLD}\u2502")
    print(f"\u2514{border}\u2518{C.END}")


def info_line(label, value, label_width=12):
    """Print a dim-label + bold-value startup info line."""
    print(f" {C.DIM}{label:<{label_width}}{C.END}{C.BOLD}{value}{C.END}")


def info_line_dim(label, value, label_width=12):
    """Print a dim-label + dim-value startup info line."""
    print(f" {C.DIM}{label:<{label_width}}{C.END}{value}")


def separator(width=50):
    """Print a dim horizontal rule."""
    print(f"{C.DIM}{'\u2500' * width}{C.END}")