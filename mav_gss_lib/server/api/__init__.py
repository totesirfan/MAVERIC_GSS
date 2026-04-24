"""
mav_gss_lib.server.api -- REST API Routes Package

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
from .identity import router as _identity_router

router = APIRouter()

router.include_router(_config_router)
router.include_router(_schema_router)
router.include_router(_queue_io_router)
router.include_router(_logs_router)
router.include_router(_session_router)
router.include_router(_identity_router)
