"""CalibratorRuntime — applies polynomial / python calibrators at decode.

Plugins are validated at construction: every PythonCalibrator's
`callable_ref` must resolve to a key in the supplied `plugins` map;
unresolved keys raise MissingPluginError. Belt-and-suspenders for the
parser's own check, so out-of-band Mission objects can't slip a missing
plugin through.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .calibrators import PolynomialCalibrator, PythonCalibrator
from .errors import MissingPluginError
from .parameter_types import (
    AggregateParameterType,
    ArrayParameterType,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
)

PluginCallable = Callable[..., tuple[Any, str]]


class CalibratorRuntime:
    __slots__ = ("_types", "_plugins")

    def __init__(
        self,
        *,
        types: Mapping[str, ParameterType],
        plugins: Mapping[str, PluginCallable],
    ) -> None:
        self._types = types
        self._plugins = plugins
        self._validate_plugins()

    def _validate_plugins(self) -> None:
        for t in self._types.values():
            cal = getattr(t, "calibrator", None)
            if isinstance(cal, PythonCalibrator) and cal.callable_ref not in self._plugins:
                raise MissingPluginError(cal.callable_ref)

    def apply(self, type_ref: str, raw: Any) -> tuple[Any, str]:
        t = self._types[type_ref]
        cal = getattr(t, "calibrator", None)
        type_unit = getattr(t, "unit", "")
        if cal is None:
            return raw, type_unit
        if isinstance(cal, PolynomialCalibrator):
            value = 0.0
            for power, coef in enumerate(cal.coefficients):
                value += coef * (raw ** power)
            return value, cal.unit or type_unit
        if isinstance(cal, PythonCalibrator):
            fn = self._plugins[cal.callable_ref]
            value, unit_from_plugin = fn(raw)
            return value, unit_from_plugin or cal.unit or type_unit
        raise TypeError(f"Unknown calibrator type {type(cal).__name__}")


__all__ = ["CalibratorRuntime", "PluginCallable"]
