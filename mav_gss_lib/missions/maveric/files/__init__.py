"""MAVERIC file-chunk subsystem.

Generalizes the imaging-only chunk pipeline into a kind-aware file
store that handles JPEG (image), JSON (aii), and NVG (mag) downlinks
through one ``ChunkFileStore`` + per-kind ``FileKindAdapter``s.

Modules
-------
- ``store.py``    — ``ChunkFileStore``: format-agnostic chunk persistence.
                    No MAVERIC imports inside; guardrail-tested.
- ``adapters.py`` — ``FileKindAdapter`` Protocol + Image/Aii/Mag adapters.
- ``repair.py``   — partial-repair and on-complete-validate primitives.
- ``registry.py`` — ``FILE_TRANSPORTS`` tuple, adapter factory, and
                    build-time validation against ``mission.meta_commands``.
- ``events.py``   — ``MavericFileChunkEvents``: single ``EventOps`` source.
- ``router.py``   — ``get_files_router``: ``/api/plugins/files`` HTTP surface.

Author:  Irfan Annuar - USC ISI SERC
"""
