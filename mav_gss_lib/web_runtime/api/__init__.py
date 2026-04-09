"""
mav_gss_lib.web_runtime.api -- REST API Routes Package

Combines sub-routers from focused route modules into a single router
that app.py can mount unchanged.

Author:  Irfan Annuar - USC ISI SERC
"""

from __future__ import annotations

from fastapi import APIRouter

from .config import router as _config_router
from .schema import router as _schema_router
from .queue_io import router as _queue_io_router
from .logs import router as _logs_router
from .session import router as _session_router

router = APIRouter()

router.include_router(_config_router)
router.include_router(_schema_router)
router.include_router(_queue_io_router)
router.include_router(_logs_router)
router.include_router(_session_router)

# Re-export helpers that tests import directly from this package
from .queue_io import list_import_files, preview_import, import_file, export_queue
from .logs import parse_replay_entry, api_log_entries
from .queue_io import parse_import_file

__all__ = [
    "router",
    "list_import_files",
    "preview_import",
    "import_file",
    "export_queue",
    "parse_import_file",
    "parse_replay_entry",
    "api_log_entries",
]
