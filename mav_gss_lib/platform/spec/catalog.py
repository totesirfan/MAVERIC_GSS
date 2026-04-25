"""CatalogBuilder — projects Mission -> per-domain catalog dicts.

Returned shape feeds GET /api/telemetry/{domain}/catalog and the alarm
framework's ParameterDecl loader. Pre-computes every domain's catalog
at construction time; the per-domain callable returns the pre-built
dict (no on-request build, no thread-safety question).
"""

from __future__ import annotations

from typing import Any, Mapping

from .bitfield import BitfieldType
from .calibrators import PolynomialCalibrator, PythonCalibrator
from .containers import ParameterRefEntry
from .mission import Mission
from .parameter_types import (
    AggregateParameterType,
    ArrayParameterType,
    EnumeratedParameterType,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
)


class CatalogBuilder:
    __slots__ = ("_mission", "_by_domain")

    def __init__(self, mission: Mission) -> None:
        self._mission = mission
        self._by_domain: dict[str, dict[str, Any]] = {}
        self._build_all()

    def for_domain(self, domain: str) -> dict[str, Any]:
        return self._by_domain.get(domain, {"params": {}})

    def _build_all(self) -> None:
        # For each container, project every emitting ParameterRefEntry into
        # the container's domain. Anonymous entries (no parameter_ref) are
        # NOT projected — catalog only carries declared parameters.
        for container in self._mission.sequence_containers.values():
            domain = container.domain
            if not domain:
                continue
            cat = self._by_domain.setdefault(domain, {"params": {}})
            for entry in container.entry_list:
                if not isinstance(entry, ParameterRefEntry):
                    continue
                if not entry.emit:
                    continue
                if entry.parameter_ref is None:
                    continue
                if entry.name in cat["params"]:
                    continue
                cat["params"][entry.name] = self._project_param(entry)

    def _project_param(self, entry: ParameterRefEntry) -> dict[str, Any]:
        param = self._mission.parameters.get(entry.parameter_ref or "", None)
        type_ref = entry.type_ref
        if type_ref in self._mission.bitfield_types:
            bf = self._mission.bitfield_types[type_ref]
            return {
                "type": type_ref,
                "unit": "",
                "description": param.description if param else "",
                "bitfield": self._project_bitfield(bf),
            }
        t = self._mission.parameter_types[type_ref]
        out: dict[str, Any] = {
            "type": type_ref,
            "unit": _resolve_unit(t),
            "description": param.description if param else "",
        }
        if isinstance(t, (IntegerParameterType, FloatParameterType)) and t.valid_range is not None:
            out["valid_range"] = list(t.valid_range)
        if isinstance(t, EnumeratedParameterType):
            out["enum_labels"] = {str(v.raw): v.label for v in t.values}
        return out

    def _project_bitfield(self, bf: BitfieldType) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for slice_entry in bf.entry_list:
            slice_meta: dict[str, Any] = {
                "bits": list(slice_entry.bits),
                "kind": slice_entry.kind,
            }
            if slice_entry.kind == "enum" and slice_entry.enum_ref:
                enum_t = self._mission.parameter_types[slice_entry.enum_ref]
                if isinstance(enum_t, EnumeratedParameterType):
                    slice_meta["enum_labels"] = {
                        str(v.raw): v.label for v in enum_t.values
                    }
            out[slice_entry.name] = slice_meta
        return out


def _resolve_unit(t: ParameterType) -> str:
    cal = getattr(t, "calibrator", None)
    if isinstance(cal, (PolynomialCalibrator, PythonCalibrator)) and cal.unit:
        return cal.unit
    return getattr(t, "unit", "")


__all__ = ["CatalogBuilder"]
