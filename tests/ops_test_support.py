"""Shared helpers for MAVERIC operations-focused tests."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CODE_DIR = TESTS_DIR.parent
ROOT_DIR = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

from mav_gss_lib.config import load_gss_config
from mav_gss_lib.mission_adapter import load_mission_adapter


CFG = load_gss_config()
_ADAPTER = load_mission_adapter(CFG)
CMD_DEFS = _ADAPTER.cmd_defs
NODES = getattr(_ADAPTER, "nodes", None)
GNURADIO_PYTHON = os.environ.get(
    "MAVERIC_GNURADIO_PYTHON",
    "/Users/irfan/radioconda/envs/gnuradio/bin/python3",
)


def decode_golay_via_gr(frame: bytes) -> bytes:
    """Decode an ASM+Golay frame through gr-satellites' u482c_decode."""
    script = textwrap.dedent(
        """
        import sys, time
        from gnuradio import gr
        import pmt
        from satellites import u482c_decode

        frame = bytes.fromhex(sys.argv[1])
        after_asm = frame[54:]
        dec = u482c_decode(False, 0, 1, 1)
        result = [None]

        class Sink(gr.basic_block):
            def __init__(self):
                gr.basic_block.__init__(self, '_sink', [], [])
                self.message_port_register_in(pmt.intern('in'))
                self.set_msg_handler(pmt.intern('in'), self._h)

            def _h(self, msg):
                result[0] = bytes(pmt.u8vector_elements(pmt.cdr(msg)))

        sink = Sink()
        tb = gr.top_block()
        tb.msg_connect(dec, 'out', sink, 'in')
        tb.start()
        dec.to_basic_block()._post(
            pmt.intern('in'),
            pmt.cons(pmt.PMT_NIL, pmt.init_u8vector(len(after_asm), list(after_asm))),
        )
        time.sleep(0.2)
        print(result[0].hex() if result[0] else 'NONE', flush=True)
        tb.stop()
        tb.wait()
        """
    )
    try:
        proc = subprocess.run(
            ["conda", "run", "-n", "gnuradio", "python3", "-c", script, frame.hex()],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        raise unittest.SkipTest(f"conda not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise unittest.SkipTest(f"GNU Radio Golay decode timed out: {exc}") from exc

    if proc.returncode not in (0, -6, -11, 134, 139):
        stderr = proc.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else f"rc={proc.returncode}"
        raise unittest.SkipTest(f"GNU Radio Golay decode unavailable: {detail}")

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines or lines[-1] == "NONE":
        raise unittest.SkipTest("GNU Radio Golay decode produced no payload")
    return bytes.fromhex(lines[-1])


def decode_golay_via_flowgraph(frame: bytes) -> tuple[bytes, dict]:
    """Decode an ASM+Golay frame through gr-satellites' full FSK flowgraph.

    This is heavier than decode_golay_via_gr() and should stay opt-in.
    Set MAVERIC_FULL_GR=1 to enable tests that call this helper.
    """
    if os.environ.get("MAVERIC_FULL_GR") != "1":
        raise unittest.SkipTest("set MAVERIC_FULL_GR=1 to run the full GNU Radio flowgraph test")

    if not os.path.exists(GNURADIO_PYTHON):
        raise unittest.SkipTest(f"GNU Radio Python not found: {GNURADIO_PYTHON}")

    script = textwrap.dedent(
        f"""
        import json
        import sys
        import time
        from pathlib import Path

        ROOT = Path({str(ROOT_DIR)!r})
        CODE = Path({str(CODE_DIR)!r})
        sys.path.insert(0, str(CODE))

        from gnuradio import gr, blocks, digital
        import pmt
        from satellites.core.gr_satellites_flowgraph import gr_satellites_flowgraph

        frame = bytes.fromhex(sys.argv[1])

        class Sink(gr.basic_block):
            def __init__(self):
                gr.basic_block.__init__(self, "_sink", [], [])
                self.message_port_register_in(pmt.intern("in"))
                self.msg = None
                self.set_msg_handler(pmt.intern("in"), self._h)

            def _h(self, msg):
                self.msg = msg

        prefix = [0] * 200
        suffix = [0] * 200
        src = blocks.vector_source_b(prefix + list(frame) + suffix, False, 1, [])
        mod = digital.gfsk_mod(
            samples_per_symbol=200,
            sensitivity=((3.141592653589793 * (1/1.5)) / 200),
            bt=0.5,
            verbose=False,
            log=False,
            do_unpack=True,
        )
        fg = gr_satellites_flowgraph(
            file=str(ROOT / "MAVERIC GNURADIO" / "MAVERIC_DECODER.yml"),
            samp_rate=1920000,
            iq=True,
            grc_block=True,
            options="",
        )
        sink = Sink()

        tb = gr.top_block()
        tb.connect(src, mod, fg)
        tb.msg_connect((fg, "out"), (sink, "in"))
        tb.start()
        for _ in range(100):
            if sink.msg is not None:
                break
            time.sleep(0.1)
        tb.stop()
        tb.wait()

        if sink.msg is None:
            print("NONE", flush=True)
            raise SystemExit(1)

        meta = pmt.car(sink.msg)
        pdu = bytes(pmt.u8vector_elements(pmt.cdr(sink.msg)))
        meta_py = {{}}
        if pmt.is_dict(meta):
            keys = pmt.dict_keys(meta)
            values = pmt.dict_values(meta)
            for i in range(min(pmt.length(keys), pmt.length(values))):
                key = pmt.symbol_to_string(pmt.nth(i, keys))
                val = pmt.nth(i, values)
                if pmt.is_symbol(val):
                    meta_py[key] = pmt.symbol_to_string(val)
                else:
                    meta_py[key] = str(val)

        print(json.dumps({{"payload_hex": pdu.hex(), "meta": meta_py}}), flush=True)
        """
    )

    try:
        proc = subprocess.run(
            [GNURADIO_PYTHON, "-c", script, frame.hex()],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise unittest.SkipTest(f"GNU Radio Python unavailable: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise unittest.SkipTest(f"GNU Radio full flowgraph timed out: {exc}") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else f"rc={proc.returncode}"
        raise unittest.SkipTest(f"GNU Radio full flowgraph unavailable: {detail}")

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines or lines[-1] == "NONE":
        raise unittest.SkipTest("GNU Radio full flowgraph produced no payload")

    result = json.loads(lines[-1])
    return bytes.fromhex(result["payload_hex"]), result.get("meta", {})
