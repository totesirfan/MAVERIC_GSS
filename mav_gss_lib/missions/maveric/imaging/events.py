"""Imaging-plugin event source.

Watches inbound packets for the three imaging commands
(`img_cnt_chunks`, `img_get_chunks`, `cam_capture`), drives the
`ImageAssembler` state (registering totals and feeding chunks) and
returns progress messages for the platform to broadcast to connected
websocket clients.

Reads from the declarative pipeline:
  - `payload.header` carries cmd_id + ptype name (resolved via codec).
  - `envelope.telemetry` carries the typed args emitted by the walker
    (filename, num_chunks, thumb_filename, thumb_num_chunks, chunk_idx,
    chunk_len). The walker emits these per the `*_res` sequence_container
    declarations in mission.yml.
  - `chunk_data` is declared `emit: false`, so it does not appear in
    envelope.telemetry. We slice it directly from `payload.args_raw`
    using chunk_len + the trailing-binary layout of img_get_chunks_res.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from mav_gss_lib.missions.maveric.codec import MaverPacketCodec
from mav_gss_lib.platform import PacketEnvelope


_IMAGING_CMDS = ("img_cnt_chunks", "img_get_chunks", "cam_capture")


@dataclass(slots=True)
class MavericImagingEvents:
    codec: MaverPacketCodec
    image_assembler: Any

    def on_packet(self, packet: PacketEnvelope) -> Iterable[dict[str, Any]]:
        payload = getattr(packet, "mission_payload", None)
        if payload is None:
            return []
        header = getattr(payload, "header", None)
        if not isinstance(header, dict):
            return []
        cmd_id = header.get("cmd_id")
        if cmd_id not in _IMAGING_CMDS:
            return []

        # ptype filter: img_get_chunks expects FILE; cam_capture and
        # img_cnt_chunks expect RES. Header carries the ptype as a
        # resolved name (str) when codec recognized it.
        expected_ptype = "FILE" if cmd_id == "img_get_chunks" else "RES"
        if header.get("ptype") != expected_ptype:
            return []

        # Build a {fragment_key: value} map from envelope.telemetry.
        # Skip display_only fragments — they're forensics, not canonical.
        args_by_key: dict[str, Any] = {}
        for f in packet.telemetry:
            if f.display_only:
                continue
            args_by_key[f.key] = f.value
        if not args_by_key:
            return []

        if cmd_id in ("img_cnt_chunks", "cam_capture"):
            return self._chunk_count_messages(args_by_key)
        return self._chunk_data_messages(args_by_key, payload)

    def on_client_connect(self) -> Iterable[dict[str, Any]]:
        """Replay current per-file progress so a fresh client sees live state
        without a separate REST roundtrip to /api/plugins/imaging/status."""
        return [self._progress_msg(fn) for fn in self.image_assembler.known_filenames()]

    def _progress_msg(self, filename: str) -> dict[str, Any]:
        received, total = self.image_assembler.progress(filename)
        return {
            "type": "imaging_progress",
            "filename": filename,
            "received": received,
            "total": total,
            "complete": self.image_assembler.is_complete(filename),
        }

    def _chunk_count_messages(self, args_by_key: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for filename_key, total_key in (
            ("filename", "num_chunks"),
            ("thumb_filename", "thumb_num_chunks"),
        ):
            filename = str(args_by_key.get(filename_key, ""))
            if not filename:
                continue
            try:
                self.image_assembler.set_total(filename, int(args_by_key.get(total_key, "")))
            except (ValueError, TypeError):
                continue
            messages.append(self._progress_msg(filename))
        return messages

    def _chunk_data_messages(
        self,
        args_by_key: dict[str, Any],
        payload: Any,
    ) -> list[dict[str, Any]]:
        filename = str(args_by_key.get("filename", ""))
        if not filename:
            return []

        try:
            chunk_idx = int(args_by_key.get("chunk_idx", ""))
        except (ValueError, TypeError):
            return []

        # chunk_len gates the trailing binary slice. img_get_chunks_res
        # layout: ascii tokens then binary tail of length chunk_len. We
        # locate the binary tail by walking past three ascii tokens
        # (filename, chunk_idx, chunk_len), each followed by a single
        # space separator.
        try:
            chunk_len = int(args_by_key.get("chunk_len", ""))
        except (ValueError, TypeError):
            chunk_len = 0

        data = _slice_chunk_data(payload, chunk_len)

        try:
            self.image_assembler.feed_chunk(
                filename,
                chunk_idx,
                data,
                chunk_size=chunk_len,
            )
        except (ValueError, TypeError):
            return []
        return [self._progress_msg(filename)]


def _slice_chunk_data(payload: Any, chunk_len: int) -> bytes:
    """Return the trailing chunk_data bytes from an img_get_chunks_res
    args_raw blob. Layout: `<filename> <chunk_idx> <chunk_len> <bytes…>`
    where the first three tokens are ASCII separated by a single space.

    The walker emits the three ascii tokens but not the trailing bytes
    (chunk_data has `emit: false`). We re-derive the binary tail by
    skipping past the first three space-separated tokens."""
    raw = getattr(payload, "args_raw", b"")
    if not raw or chunk_len <= 0:
        return b""
    # Walk past 3 spaces to land at the first byte of chunk_data.
    pos = 0
    for _ in range(3):
        sp = raw.find(b" ", pos)
        if sp < 0:
            return b""
        pos = sp + 1
    return bytes(raw[pos:pos + chunk_len])
