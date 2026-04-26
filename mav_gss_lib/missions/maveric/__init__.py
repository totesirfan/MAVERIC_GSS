"""MAVERIC mission package for the MissionSpec runtime."""

from .declarative import (
    DeclarativeCapabilities,
    build_declarative_capabilities,
)

__all__ = ("DeclarativeCapabilities", "build_declarative_capabilities")
