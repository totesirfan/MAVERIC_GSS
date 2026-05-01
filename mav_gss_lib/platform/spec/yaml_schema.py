"""Pydantic v2 input schema for mission.yml.

This is the first-pass shape check. The detail-pass dataclass projection
(yaml_parse.py) handles graph rules (cycles, conflicts, abstract-without-children)
that pydantic alone can't express.

Authors edit YAML; pydantic produces path-precise errors on shape
violations. yaml_parse.py wraps those with line numbers from the
ruamel/SafeLoader mark map.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class _PolynomialCalibrator(_Strict):
    polynomial: tuple[float, ...]
    unit: str = ""


class _PythonCalibrator(_Strict):
    python: str
    unit: str = ""


_CalibratorYaml = _PolynomialCalibrator | _PythonCalibrator | None


class _IntegerType(_Strict):
    kind: Literal["int"]
    size_bits: Literal[8, 16, 32, 64]
    signed: bool = False
    byte_order: Literal["little", "big"] = "little"
    calibrator: _CalibratorYaml = None
    unit: str = ""
    valid_range: tuple[float, float] | None = None
    description: str = ""
    # Default: ascii_tokens reads ONE decimal token per int. With
    # `u8_tokens`, the ascii path reads size_bits/8 decimal u8 tokens
    # and packs them in declared byte_order before decoding as int.
    wire_format: Literal["single_token", "u8_tokens"] = "single_token"


class _FloatType(_Strict):
    kind: Literal["float"]
    size_bits: Literal[32, 64] = 32
    byte_order: Literal["little", "big"] = "little"
    calibrator: _CalibratorYaml = None
    unit: str = ""
    valid_range: tuple[float, float] | None = None
    description: str = ""


class _StringType(_Strict):
    kind: Literal["string"]
    encoding: Literal["fixed", "null_terminated", "to_end", "ascii_token"]
    fixed_size_bytes: int | None = None
    charset: str = "UTF-8"
    description: str = ""


class _BinaryType(_Strict):
    kind: Literal["binary"]
    size: dict
    description: str = ""


class _EnumType(_Strict):
    kind: Literal["enum"]
    size_bits: Literal[8, 16, 32, 64] = 8
    signed: bool = False
    byte_order: Literal["little", "big"] = "little"
    values: dict[int, str]
    description: str = ""


class _AbsoluteTimeType(_Strict):
    kind: Literal["absolute_time"]
    encoding: Literal["millis_u64"]
    epoch: Literal["unix"] = "unix"
    byte_order: Literal["little", "big"] = "little"
    description: str = ""


class _AggregateMember(_Strict):
    name: str
    type: str


class _AggregateType(_Strict):
    kind: Literal["aggregate"]
    member_list: list[_AggregateMember]
    unit: str = ""
    description: str = ""


class _ArrayType(_Strict):
    kind: Literal["array"]
    array_type_ref: str
    dimension_list: list[int]
    unit: str = ""
    description: str = ""


_ParameterTypeYaml = (
    _IntegerType | _FloatType | _StringType | _BinaryType
    | _EnumType | _AbsoluteTimeType | _AggregateType | _ArrayType
)


class _BitfieldEntry(_Strict):
    name: str
    bits: tuple[int, int]
    kind: Literal["bool", "uint", "int", "enum"] = "bool"
    enum_ref: str | None = None
    unit: str = ""


class _BitfieldType(_Strict):
    size_bits: Literal[8, 16, 32, 64]
    byte_order: Literal["little", "big"] = "little"
    entry_list: list[_BitfieldEntry] = Field(default_factory=list)


class _Parameter(_Strict):
    type: str
    description: str = ""
    domain: str | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    alarm: Any | None = None


class _ParameterRefEntry(_Strict):
    name: str
    type: str
    emit: bool = True


class _RepeatEntry(_Strict):
    repeat_entry: dict


class _PagedFrameEntry(_Strict):
    paged_frame_entry: dict


_EntryYaml = _ParameterRefEntry | _RepeatEntry | _PagedFrameEntry


class _SequenceContainer(_Strict):
    domain: str
    layout: Literal["binary", "ascii_tokens"] = "ascii_tokens"
    abstract: bool = False
    base_container_ref: str | None = None
    restriction_criteria: dict | None = None
    entry_list: list[dict] = Field(default_factory=list)
    on_short_payload: Literal["skip", "raise", "emit_partial"] = "skip"
    on_decode_error: Literal["skip", "raise", "emit_partial"] = "raise"
    description: str = ""
    stale: dict[str, Any] | None = None
    expected_period_ms: int | None = None


class _Argument(_Strict):
    name: str
    type: str
    description: str = ""
    valid_range: tuple[float, float] | None = None
    valid_values: list[Any] | None = None
    invalid_values: list[Any] | None = None
    important: bool = False


class _VerifierWindow(_Strict):
    start_ms: int = 0
    stop_ms: int = 30_000


class _VerifierSpecDecl(_Strict):
    stage: Literal["received", "accepted", "complete", "failed"]
    label: str
    tone: Literal["info", "success", "warning", "danger"]
    window: _VerifierWindow = Field(default_factory=_VerifierWindow)


class _VerifierRules(_Strict):
    selector: str = ""
    by_key: dict[str, list[str]] = Field(default_factory=dict)


class _VerifierOverrideByKey(_Strict):
    selector: str = ""
    by_key: dict[str, list[str]] = Field(default_factory=dict)


_VerifierOverrideValue = list[str] | _VerifierOverrideByKey


class _MetaCommand(_Strict):
    packet: dict[str, Any] = Field(default_factory=dict)
    allowed_packet: dict[str, list[Any]] = Field(default_factory=dict)
    guard: bool = False
    no_response: bool = False
    rx_only: bool = False
    deprecated: bool = False
    argument_list: list[_Argument] = Field(default_factory=list)
    rx_args: list[_Argument] = Field(default_factory=list)
    rx_count_from: str | None = None
    rx_index_field: str | None = None
    description: str = ""
    verifier_override: dict[str, _VerifierOverrideValue] | None = None


class _Header(_Strict):
    version: str
    date: str
    description: str = ""


class MissionDocument(_Strict):
    schema_version: int
    id: str
    name: str
    header: _Header

    extensions: dict[str, Any] = Field(default_factory=dict)

    parameter_types: dict[str, _ParameterTypeYaml] = Field(default_factory=dict)
    parameters: dict[str, _Parameter] = Field(default_factory=dict)
    bitfield_types: dict[str, _BitfieldType] = Field(default_factory=dict)
    sequence_containers: dict[str, _SequenceContainer] = Field(default_factory=dict)
    meta_commands: dict[str, _MetaCommand] = Field(default_factory=dict)
    verifier_specs: dict[str, _VerifierSpecDecl] = Field(default_factory=dict)
    verifier_rules: _VerifierRules | None = None
    framing: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unsupported schema_version {v} (this parser handles v1)")
        return v


__all__ = ["MissionDocument"]
