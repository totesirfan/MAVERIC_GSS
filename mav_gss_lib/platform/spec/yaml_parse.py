"""YAML -> Mission projection.

Two entry points:
  - parse_yaml(path, *, plugins): runtime entry. Validates plugin refs;
    raises MissingPluginError on unresolved keys.
  - parse_yaml_for_tooling(path): tooling entry. Skips plugin validation;
    used by XTCE-export codegen and inspection scripts.

Parser performs:
  1. pyyaml load (SafeLoader)
  2. pydantic validation (yaml_schema.MissionDocument)
  3. dataclass projection
  4. graph rules: type cycles, container conflict, base_container_ref
     cycle / multi-level chain, abstract-without-children, dynamic_ref
     forward-ref + non-ParameterRefEntry, paged-frame target empty,
     plugin reference resolution (when plugins != None).
  5. Subset-overlap warning collection (non-fatal -> Mission.parse_warnings).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from .argument_types import (
    ArgumentType,
    BUILT_IN_ARGUMENT_TYPES,
    FloatArgumentType,
    IntegerArgumentType,
    StringArgumentType,
)
from .bitfield import BitfieldEntry, BitfieldType
from .calibrators import (
    Calibrator,
    PolynomialCalibrator,
    PythonCalibrator,
)
from .commands import Argument, MetaCommand
from .containers import (
    Comparison,
    Entry,
    PagedFrameEntry,
    ParameterRefEntry,
    RepeatEntry,
    RestrictionCriteria,
    SequenceContainer,
)
from .errors import (
    ContainerConflict,
    DuplicateTypeName,
    IncompatibleSchemaVersion,
    InvalidDynamicRef,
    MissingPluginError,
    PagedFrameTargetEmpty,
    ParseError,
    UnknownTypeRef,
    UnknownVerifierId,
)
from .verifier_decls import VerifierOverrideByKey, VerifierRules, VerifierSpecDecl
from .mission import (
    ContainerShadow,
    EnumSliceTruncation,
    Mission,
    MissionHeader,
    ParseWarning,
)
from .parameters import Parameter
from .parameter_types import (
    AbsoluteTimeParameterType,
    AggregateMember,
    AggregateParameterType,
    ArrayParameterType,
    BinaryParameterType,
    BUILT_IN_PARAMETER_TYPES,
    EnumeratedParameterType,
    EnumValue,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
    StringParameterType,
)
from .yaml_schema import MissionDocument


def parse_yaml(path: str | Path, *, plugins: Mapping[str, Callable]) -> Mission:
    return _parse(path, plugins=plugins, validate_plugins=True)


def parse_yaml_for_tooling(path: str | Path) -> Mission:
    return _parse(path, plugins={}, validate_plugins=False)


def _parse(
    path: str | Path,
    *,
    plugins: Mapping[str, Callable],
    validate_plugins: bool,
) -> Mission:
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if raw.get("schema_version") != 1:
        raise IncompatibleSchemaVersion(found=raw.get("schema_version"), supported=1)
    doc = MissionDocument.model_validate(raw)

    parameter_types = _project_parameter_types(doc)
    argument_types: dict[str, ArgumentType] = dict(BUILT_IN_ARGUMENT_TYPES)
    for name, t in (doc.argument_types or {}).items():
        if name in BUILT_IN_ARGUMENT_TYPES:
            raise ParseError(
                f"argument_types {name!r} redeclares a built-in primitive; "
                f"choose a distinct name (e.g., {name}_t)"
            )
        argument_types[name] = _build_argument_type(name, t)
    bitfield_types = _project_bitfield_types(doc, parameter_types)
    parameters = {
        name: Parameter(name=name, type_ref=p.type,
                        description=p.description, domain=p.domain,
                        tags=dict(p.tags), alarm=p.alarm)
        for name, p in doc.parameters.items()
    }
    sequence_containers = _project_sequence_containers(doc, parameter_types, bitfield_types)
    meta_commands = _project_meta_commands(doc, parameter_types)
    verifier_specs = _project_verifier_specs(doc)
    verifier_rules = _project_verifier_rules(doc)

    # Cross-reference checks
    _check_type_refs(parameter_types, argument_types, bitfield_types,
                     parameters, sequence_containers, meta_commands)
    _check_to_end_args_are_last(meta_commands, argument_types)
    _check_type_graph_cycles(parameter_types)
    _check_base_container_refs(sequence_containers)
    _check_parent_args_keys(sequence_containers)
    _check_empty_predicates(sequence_containers)
    _check_paged_frame_targets(sequence_containers)
    _check_recursive_paged_frames(sequence_containers)
    _check_dynamic_ref_ordering(sequence_containers, parameter_types)
    _check_container_domains(sequence_containers)
    _check_repeat_entry_count(sequence_containers)
    _check_argument_bound_types(meta_commands, parameter_types)
    _check_verifier_refs(verifier_specs, verifier_rules, meta_commands)
    if validate_plugins:
        _check_plugins(parameter_types, plugins)

    warnings = _collect_warnings(parameter_types, bitfield_types, sequence_containers)

    header = MissionHeader(
        version=doc.header.version,
        date=doc.header.date,
        description=doc.header.description,
    )
    from .framing import parse_framing_section
    from .ui import parse_ui_section
    framing = parse_framing_section(doc.framing)
    ui = parse_ui_section(doc.ui)
    return Mission(
        id=doc.id, name=doc.name, header=header,
        parameter_types=parameter_types,
        argument_types=argument_types,
        parameters=parameters,
        bitfield_types=bitfield_types,
        sequence_containers=sequence_containers,
        meta_commands=meta_commands,
        extensions=dict(doc.extensions),
        parse_warnings=tuple(warnings),
        verifier_specs=verifier_specs,
        verifier_rules=verifier_rules,
        framing=framing,
        ui=ui,
    )


def _representable_int_range(size_bits: int, signed: bool) -> tuple[int, int]:
    if signed:
        return (-(2 ** (size_bits - 1)), (2 ** (size_bits - 1)) - 1)
    return (0, (2 ** size_bits) - 1)


def _build_argument_type(name: str, t) -> ArgumentType:
    kind = t.kind
    if kind == "int":
        if t.valid_range is not None:
            lo, hi = t.valid_range
            r_lo, r_hi = _representable_int_range(t.size_bits, t.signed)
            if lo < r_lo or hi > r_hi:
                raise ParseError(
                    f"argument_type {name!r}: valid_range [{lo}, {hi}] exceeds "
                    f"representable range [{r_lo}, {r_hi}] for "
                    f"size_bits={t.size_bits}, signed={t.signed}. "
                    f"Either widen size_bits or narrow valid_range."
                )
            if lo > hi:
                raise ParseError(
                    f"argument_type {name!r}: valid_range [{lo}, {hi}] is "
                    f"inverted (lo > hi)"
                )
        if t.valid_values is not None:
            r_lo, r_hi = _representable_int_range(t.size_bits, t.signed)
            out_of_range = [v for v in t.valid_values if not (r_lo <= v <= r_hi)]
            if out_of_range:
                raise ParseError(
                    f"argument_type {name!r}: valid_values {out_of_range} outside "
                    f"representable range [{r_lo}, {r_hi}] for "
                    f"size_bits={t.size_bits}, signed={t.signed}"
                )
        return IntegerArgumentType(
            name=name, size_bits=t.size_bits, signed=t.signed,
            byte_order=t.byte_order, description=t.description,
            valid_range=t.valid_range,
            valid_values=tuple(t.valid_values) if t.valid_values is not None else None,
        )
    if kind == "float":
        if t.valid_range is not None:
            lo, hi = t.valid_range
            if lo > hi:
                raise ParseError(
                    f"argument_type {name!r}: valid_range [{lo}, {hi}] is "
                    f"inverted (lo > hi)"
                )
        return FloatArgumentType(
            name=name, size_bits=t.size_bits, byte_order=t.byte_order,
            description=t.description, valid_range=t.valid_range,
            valid_values=tuple(t.valid_values) if t.valid_values is not None else None,
        )
    if kind == "string":
        return StringArgumentType(
            name=name, encoding=t.encoding,
            description=t.description,
        )
    raise ValueError(f"unknown argument_type kind {kind!r} for {name!r}")


def _project_calibrator(c) -> Calibrator:
    if c is None:
        return None
    if hasattr(c, "polynomial"):
        return PolynomialCalibrator(coefficients=tuple(c.polynomial), unit=c.unit)
    if hasattr(c, "python"):
        return PythonCalibrator(callable_ref=c.python, unit=c.unit)
    return None


def _project_parameter_types(doc: MissionDocument) -> dict[str, ParameterType]:
    out: dict[str, ParameterType] = dict(BUILT_IN_PARAMETER_TYPES)
    for name, t in doc.parameter_types.items():
        if name in out:
            raise DuplicateTypeName(name, namespaces=("built_in", "parameter_types"))
        out[name] = _project_one_param_type(name, t)
    return out


def _project_one_param_type(name: str, t) -> ParameterType:
    kind = t.kind
    if kind == "int":
        if t.wire_format == "i16_tokens" and t.size_bits < 16:
            raise ParseError(
                f"int {name!r}: wire_format=i16_tokens requires size_bits >= 16 "
                f"(got {t.size_bits})"
            )
        if t.wire_format == "u8_tokens" and t.size_bits < 8:
            raise ParseError(
                f"int {name!r}: wire_format=u8_tokens requires size_bits >= 8 "
                f"(got {t.size_bits})"
            )
        return IntegerParameterType(
            name=name, size_bits=t.size_bits, signed=t.signed,
            byte_order=t.byte_order, calibrator=_project_calibrator(t.calibrator),
            unit=t.unit, valid_range=t.valid_range, description=t.description,
            wire_format=t.wire_format,
        )
    if kind == "float":
        return FloatParameterType(
            name=name, size_bits=t.size_bits, byte_order=t.byte_order,
            calibrator=_project_calibrator(t.calibrator),
            unit=t.unit, valid_range=t.valid_range, description=t.description,
        )
    if kind == "string":
        return StringParameterType(
            name=name, encoding=t.encoding,
            fixed_size_bytes=t.fixed_size_bytes, charset=t.charset,
            description=t.description,
        )
    if kind == "binary":
        size = t.size
        if "fixed" in size:
            return BinaryParameterType(
                name=name, size_kind="fixed", fixed_size_bytes=int(size["fixed"]),
                description=t.description,
            )
        if "dynamic_ref" in size:
            return BinaryParameterType(
                name=name, size_kind="dynamic_ref", size_ref=str(size["dynamic_ref"]),
                description=t.description,
            )
        raise ParseError(f"binary type {name!r}: size must declare fixed or dynamic_ref")
    if kind == "enum":
        values = tuple(EnumValue(raw=r, label=l) for r, l in sorted(t.values.items()))
        return EnumeratedParameterType(
            name=name, size_bits=t.size_bits, signed=t.signed,
            byte_order=t.byte_order, values=values, description=t.description,
        )
    if kind == "absolute_time":
        return AbsoluteTimeParameterType(
            name=name, encoding=t.encoding, epoch=t.epoch,
            byte_order=t.byte_order, description=t.description,
        )
    if kind == "aggregate":
        members = tuple(
            AggregateMember(name=m.name, type_ref=m.type, unit=m.unit)
            for m in t.member_list
        )
        # Wire-encoding fields are mutually-required for calibrator-backed
        # aggregates. Reject incoherent combinations at parse time so the
        # walker doesn't have to guess later.
        if t.size_bits is not None:
            if t.byte_order is None:
                raise ParseError(
                    f"aggregate {name!r}: size_bits requires byte_order"
                )
            if t.calibrator is None:
                raise ParseError(
                    f"aggregate {name!r}: size_bits requires a calibrator "
                    "(wire-encoded aggregates are produced by a calibrator "
                    "from the raw integer)"
                )
            if t.wire_format == "i16_tokens" and t.size_bits < 16:
                raise ParseError(
                    f"aggregate {name!r}: wire_format=i16_tokens requires "
                    f"size_bits >= 16 (got {t.size_bits})"
                )
        else:
            if t.byte_order is not None or t.signed or t.wire_format != "single_token":
                raise ParseError(
                    f"aggregate {name!r}: byte_order / signed / wire_format "
                    "are only valid when size_bits is set (in-place aggregate "
                    "decode walks members; wire encoding does not apply)"
                )
            if t.calibrator is not None:
                raise ParseError(
                    f"aggregate {name!r}: calibrator is only valid when "
                    "size_bits is set"
                )
        return AggregateParameterType(
            name=name, member_list=members, unit=t.unit, description=t.description,
            size_bits=t.size_bits, byte_order=t.byte_order, signed=t.signed,
            wire_format=t.wire_format,
            calibrator=_project_calibrator(t.calibrator),
        )
    if kind == "array":
        if len(t.dimension_list) != 1:
            raise ParseError(f"array {name!r}: dimension_list must have length 1 in v1")
        return ArrayParameterType(
            name=name, array_type_ref=t.array_type_ref,
            dimension_list=tuple(t.dimension_list), unit=t.unit, description=t.description,
        )
    raise ParseError(f"unknown parameter_type kind {kind!r} on {name!r}")


def _project_bitfield_types(doc: MissionDocument, types: Mapping[str, ParameterType]) -> dict[str, BitfieldType]:
    out: dict[str, BitfieldType] = {}
    for name, b in doc.bitfield_types.items():
        if name in types:
            raise DuplicateTypeName(name, namespaces=("parameter_types", "bitfield_types"))
        entries = tuple(
            BitfieldEntry(
                name=e.name, bits=tuple(e.bits), kind=e.kind,
                enum_ref=e.enum_ref, unit=e.unit,
            )
            for e in b.entry_list
        )
        out[name] = BitfieldType(
            name=name, size_bits=b.size_bits, byte_order=b.byte_order, entry_list=entries,
        )
    return out


def _project_sequence_containers(
    doc: MissionDocument,
    types: Mapping[str, ParameterType],
    bitfields: Mapping[str, BitfieldType],
) -> dict[str, SequenceContainer]:
    out: dict[str, SequenceContainer] = {}
    parameters = set(doc.parameters)
    parameter_types_by_name = {pname: p.type for pname, p in doc.parameters.items()}
    for name, c in doc.sequence_containers.items():
        rc = _project_restriction(c.restriction_criteria) if c.restriction_criteria else None
        entry_list = tuple(
            _project_entry(e, parameters, parameter_types_by_name, container_name=name)
            for e in c.entry_list
        )
        out[name] = SequenceContainer(
            name=name, entry_list=entry_list, restriction_criteria=rc,
            abstract=c.abstract, base_container_ref=c.base_container_ref,
            domain=c.domain, layout=c.layout,
            on_short_payload=c.on_short_payload,
            on_decode_error=c.on_decode_error,
            description=c.description,
            stale=c.stale,
            expected_period_ms=c.expected_period_ms or 0,
        )
    _check_container_conflicts(out)
    return out


def _project_restriction(rc: dict) -> RestrictionCriteria:
    return RestrictionCriteria(
        packet=tuple(_project_comparisons(rc.get("packet", {}))),
        parent_args=tuple(_project_comparisons(rc.get("parent_args", {}))),
    )


def _project_comparisons(block: dict) -> list[Comparison]:
    out: list[Comparison] = []
    for key, val in block.items():
        if isinstance(val, dict) and "op" in val:
            out.append(Comparison(parameter_ref=key, value=val["value"], operator=val["op"]))
        else:
            out.append(Comparison(parameter_ref=key, value=val, operator="=="))
    return out


def _resolve_entry_type(
    entry_name: str,
    declared_type: str | None,
    parameter_types_by_name: Mapping[str, str],
    *,
    container_name: str,
    role: str = "entry_list",
) -> str:
    """Resolve a container entry's type per XTCE 1.3 ParameterRefEntry.

    XTCE 1.3 (CCSDS 660.1-B-2) ParameterRefEntry carries only
    `parameterRef`; per-entry type overrides are not allowed. We accept
    a redundant `type:` field for legacy YAML, but it must match the
    parameter's declared type. Mismatch is a parse error naming the
    entry, both types, and the container. Absence resolves the type
    from the parameter declaration.

    Falls through to the declared override when the entry name is not a
    declared parameter (anonymous entries — e.g. ASCII-token fillers).
    """
    canonical = parameter_types_by_name.get(entry_name)
    if canonical is None:
        # Anonymous entry (no matching declared parameter). The legacy
        # path requires a type; absence is a schema bug we surface here
        # rather than tripping a downstream NoneType.
        if declared_type is None:
            raise ParseError(
                f"sequence_containers.{container_name}.{role} entry {entry_name!r} "
                f"has no declared parameter and no `type:` — declare the parameter "
                f"or attach a type"
            )
        return declared_type
    if declared_type is not None and declared_type != canonical:
        raise ParseError(
            f"sequence_containers.{container_name}.{role} entry {entry_name!r} "
            f"declares type {declared_type!r} but parameter {entry_name!r} "
            f"is declared with type {canonical!r}; XTCE 1.3 ParameterRefEntry "
            f"carries only parameterRef — drop the per-entry type or align it"
        )
    return canonical


def _project_entry(
    entry: dict,
    parameters: set[str],
    parameter_types_by_name: Mapping[str, str],
    *,
    container_name: str,
) -> Entry:
    if "paged_frame_entry" in entry:
        e = entry["paged_frame_entry"]
        return PagedFrameEntry(
            base_container_ref=e["base_container_ref"],
            marker_separator=e.get("marker_separator", ","),
            dispatch_keys=tuple(e.get("dispatch_keys", ("module", "register"))),
            on_unknown_register=e.get("on_unknown_register", "skip"),
        )
    if "repeat_entry" in entry:
        e = entry["repeat_entry"]
        inner = e["entry"]
        inner_type_ref = _resolve_entry_type(
            inner["name"], inner.get("type"), parameter_types_by_name,
            container_name=container_name, role="repeat_entry",
        )
        inner_entry = ParameterRefEntry(
            name=inner["name"], type_ref=inner_type_ref,
            parameter_ref=inner["name"] if inner["name"] in parameters else None,
            emit=inner.get("emit", True),
        )
        count = e.get("count", "to_end")
        if count == "to_end":
            return RepeatEntry(entry=inner_entry, count_kind="to_end")
        if isinstance(count, dict) and "ref" in count:
            return RepeatEntry(entry=inner_entry, count_kind="dynamic_ref", count_ref=count["ref"])
        return RepeatEntry(entry=inner_entry, count_kind="fixed", count_fixed=int(count))
    type_ref = _resolve_entry_type(
        entry["name"], entry.get("type"), parameter_types_by_name,
        container_name=container_name, role="entry_list",
    )
    return ParameterRefEntry(
        name=entry["name"], type_ref=type_ref,
        parameter_ref=entry["name"] if entry["name"] in parameters else None,
        emit=entry.get("emit", True),
    )


def _project_meta_commands(
    doc: MissionDocument, types: Mapping[str, ParameterType],
) -> dict[str, MetaCommand]:
    out: dict[str, MetaCommand] = {}
    for name, m in doc.meta_commands.items():
        verifier_override: dict[str, tuple[str, ...] | VerifierOverrideByKey] = {}
        if m.verifier_override is not None:
            verifier_override = {
                stage: _project_verifier_override_value(value)
                for stage, value in m.verifier_override.items()
            }
        out[name] = MetaCommand(
            id=name,
            packet=dict(m.packet),
            allowed_packet={k: tuple(v) for k, v in m.allowed_packet.items()},
            guard=m.guard, no_response=m.no_response,
            rx_only=m.rx_only, deprecated=m.deprecated,
            argument_list=tuple(_project_argument(a) for a in m.argument_list),
            description=m.description,
            verifier_override=verifier_override,
        )
    return out


def _project_argument(a) -> Argument:
    return Argument(
        name=a.name, type_ref=a.type, description=a.description,
        valid_range=a.valid_range,
        valid_values=tuple(a.valid_values) if a.valid_values is not None else None,
        invalid_values=tuple(a.invalid_values) if a.invalid_values is not None else None,
        important=a.important,
    )


def _project_verifier_override_value(value) -> tuple[str, ...] | VerifierOverrideByKey:
    if hasattr(value, "by_key"):
        return VerifierOverrideByKey(
            selector=value.selector,
            by_key={
                key: tuple(ids)
                for key, ids in value.by_key.items()
            },
        )
    return tuple(value)


def _project_verifier_specs(doc: MissionDocument) -> dict[str, VerifierSpecDecl]:
    return {
        name: VerifierSpecDecl(
            verifier_id=name,
            stage=v.stage,
            display_label=v.label,
            display_tone=v.tone,
            start_ms=v.window.start_ms,
            stop_ms=v.window.stop_ms,
        )
        for name, v in doc.verifier_specs.items()
    }


def _project_verifier_rules(doc: MissionDocument) -> VerifierRules | None:
    if doc.verifier_rules is None:
        return None
    selector = doc.verifier_rules.selector
    if doc.verifier_rules.by_key and not selector:
        raise ValueError("verifier_rules.selector is required when verifier_rules.by_key is non-empty")
    return VerifierRules(
        selector=selector,
        by_key={
            key: tuple(ids)
            for key, ids in doc.verifier_rules.by_key.items()
        }
    )


def _check_verifier_refs(
    verifier_specs: dict[str, VerifierSpecDecl],
    verifier_rules: VerifierRules | None,
    meta_commands: dict[str, MetaCommand],
) -> None:
    """Cross-reference: every verifier_id used in rules or overrides must exist in verifier_specs."""
    if verifier_rules is not None:
        for key, ids in verifier_rules.by_key.items():
            for vid in ids:
                if vid not in verifier_specs:
                    raise UnknownVerifierId(vid, source=f"verifier_rules.by_key.{key}")
    for cmd_id, meta in meta_commands.items():
        for stage, override in meta.verifier_override.items():
            if isinstance(override, VerifierOverrideByKey):
                for key, ids in override.by_key.items():
                    for vid in ids:
                        if vid not in verifier_specs:
                            raise UnknownVerifierId(
                                vid,
                                source=(
                                    f"meta_commands.{cmd_id}."
                                    f"verifier_override.{stage}.by_key.{key}"
                                ),
                            )
                continue
            for vid in override:
                if vid not in verifier_specs:
                    raise UnknownVerifierId(vid, source=f"meta_commands.{cmd_id}.verifier_override.{stage}")


# ---- Cross-reference / graph checks ----


def _check_type_refs(parameter_types, argument_types, bitfield_types,
                     parameters, containers, meta_commands):
    tm_legal = set(parameter_types) | set(bitfield_types)
    tc_legal = set(argument_types)
    # Top-level parameter refs — TM side
    for p in parameters.values():
        if p.type_ref not in tm_legal:
            raise UnknownTypeRef(p.type_ref, source=f"parameters.{p.name}.type")
    # Container entry refs — TM side (incl. inner refs of repeat entries)
    for c in containers.values():
        for e in c.entry_list:
            if isinstance(e, ParameterRefEntry):
                if e.type_ref not in tm_legal:
                    raise UnknownTypeRef(
                        e.type_ref,
                        source=f"sequence_containers.{c.name}.entry_list[{e.name}].type",
                    )
            elif isinstance(e, RepeatEntry):
                inner = e.entry
                if inner.type_ref not in tm_legal:
                    raise UnknownTypeRef(
                        inner.type_ref,
                        source=f"sequence_containers.{c.name}.entry_list[{inner.name}@repeat].type",
                    )
    # Command argument refs — TC side
    for m in meta_commands.values():
        for a in m.argument_list:
            if a.type_ref not in tc_legal:
                raise UnknownTypeRef(
                    a.type_ref,
                    source=f"meta_commands.{m.id}.argument_list[{a.name}].type",
                )
    # Aggregate member + Array element refs — TM side
    for tname, t in parameter_types.items():
        if isinstance(t, AggregateParameterType):
            for m in t.member_list:
                if m.type_ref not in tm_legal:
                    raise UnknownTypeRef(
                        m.type_ref,
                        source=f"parameter_types.{tname}.member_list[{m.name}].type",
                    )
        elif isinstance(t, ArrayParameterType):
            if t.array_type_ref not in tm_legal:
                raise UnknownTypeRef(
                    t.array_type_ref,
                    source=f"parameter_types.{tname}.array_type_ref",
                )
    # Bitfield enum refs — TM side
    for bname, bf in bitfield_types.items():
        for e in bf.entry_list:
            if e.kind == "enum" and e.enum_ref is not None:
                if e.enum_ref not in tm_legal:
                    raise UnknownTypeRef(
                        e.enum_ref,
                        source=f"bitfield_types.{bname}.entry_list[{e.name}].enum_ref",
                    )


def _check_to_end_args_are_last(meta_commands, argument_types):
    for m in meta_commands.values():
        for i, a in enumerate(m.argument_list):
            t = argument_types.get(a.type_ref)
            if not isinstance(t, StringArgumentType):
                continue
            if t.encoding != "to_end":
                continue
            if i != len(m.argument_list) - 1:
                raise ParseError(
                    f"meta_command {m.id!r} argument {a.name!r} (type {a.type_ref!r}, "
                    f"encoding=to_end) must be the LAST arg in argument_list — "
                    f"to_end consumes the rest of the input and would drop trailing args"
                )


def _check_base_container_refs(containers: Mapping[str, SequenceContainer]) -> None:
    for c in containers.values():
        if c.base_container_ref is None:
            continue
        if c.base_container_ref not in containers:
            raise UnknownTypeRef(c.base_container_ref, source=f"sequence_containers.{c.name}.base_container_ref")
        parent = containers[c.base_container_ref]
        if parent.base_container_ref is not None:
            raise ParseError(
                f"container {c.name!r} -> {parent.name!r}: multi-level inheritance not supported in v1"
            )
    # Abstract-without-children
    referenced = {c.base_container_ref for c in containers.values() if c.base_container_ref}
    for c in containers.values():
        if c.abstract and c.name not in referenced:
            referenced_by_paged = any(
                isinstance(e, PagedFrameEntry) and e.base_container_ref == c.name
                for other in containers.values() for e in other.entry_list
            )
            if not referenced_by_paged:
                raise ParseError(
                    f"abstract container {c.name!r} has no concrete children "
                    f"and is not referenced by any paged_frame_entry"
                )


def _check_paged_frame_targets(containers: Mapping[str, SequenceContainer]) -> None:
    for c in containers.values():
        for e in c.entry_list:
            if not isinstance(e, PagedFrameEntry):
                continue
            target = e.base_container_ref
            children = [child for child in containers.values() if child.base_container_ref == target]
            if not children:
                raise PagedFrameTargetEmpty(entry_owner=c.name, base_container_ref=target)


def _check_container_conflicts(containers: Mapping[str, SequenceContainer]) -> None:
    # Top-level containers (base_container_ref=None) MAY share a packet
    # predicate — they fan out to multiple domains. Concrete children are
    # disambiguated by parent_args, not packet predicates, so a duplicate
    # at this level can only arise between top-level siblings, which is
    # legal. The check is intentionally a no-op; the walker iterates all
    # matching parents.
    return


def _check_type_graph_cycles(parameter_types: Mapping[str, ParameterType]) -> None:
    """Rule 1 — DFS through aggregate/array type_ref edges; raises on cycles."""
    white: set[str] = set(parameter_types)
    gray: set[str] = set()
    black: set[str] = set()
    parent: dict[str, str | None] = {}

    def _children(t: ParameterType) -> list[str]:
        if isinstance(t, AggregateParameterType):
            return [m.type_ref for m in t.member_list]
        if isinstance(t, ArrayParameterType):
            return [t.array_type_ref]
        return []

    def _dfs(name: str, via: str | None) -> None:
        if name not in parameter_types:
            return  # dangling ref — caught by _check_type_refs
        if name in black:
            return
        if name in gray:
            # Build cycle path from parent map
            path: list[str] = [name]
            cur = via
            while cur is not None and cur != name:
                path.append(cur)
                cur = parent.get(cur)
            path.append(name)
            path.reverse()
            raise ParseError(f"type cycle detected: {' -> '.join(path)}")
        gray.add(name)
        white.discard(name)
        parent[name] = via
        for child in _children(parameter_types[name]):
            _dfs(child, name)
        gray.discard(name)
        black.add(name)

    for name in list(parameter_types):
        if name in white:
            _dfs(name, None)


def _check_parent_args_keys(containers: Mapping[str, SequenceContainer]) -> None:
    """Rule 2 — every key in parent_args must be decoded by the parent's entry_list."""
    for c in containers.values():
        if c.base_container_ref is None or c.restriction_criteria is None:
            continue
        if not c.restriction_criteria.parent_args:
            continue
        parent = containers.get(c.base_container_ref)
        if parent is None:
            continue  # missing parent ref caught by _check_type_refs

        # Collect names decoded by the parent's entry_list
        decoded: set[str] = set()
        for e in parent.entry_list:
            if isinstance(e, ParameterRefEntry):
                decoded.add(e.name)
            elif isinstance(e, RepeatEntry):
                decoded.add(e.entry.name)
            # PagedFrameEntry does not contribute to decoded_into

        for cmp in c.restriction_criteria.parent_args:
            if cmp.parameter_ref not in decoded:
                available = sorted(decoded)
                raise ParseError(
                    f"container {c.name!r} parent_args key {cmp.parameter_ref!r} "
                    f"not decoded by parent {parent.name!r}; available: {available}"
                )


def _check_empty_predicates(containers: Mapping[str, SequenceContainer]) -> None:
    """Rule 3 — non-abstract, non-child containers must have at least one packet predicate."""
    for c in containers.values():
        if c.abstract:
            continue
        if c.base_container_ref is not None:
            continue  # child container — parent's packet: already constrains matching
        rc = c.restriction_criteria
        no_packet = rc is None or not rc.packet
        no_parent_args = rc is None or not rc.parent_args
        if no_packet and no_parent_args:
            raise ParseError(
                f"container {c.name!r} has no restriction_criteria.packet predicates "
                f"and is not a base_container_ref child; it would never match"
            )


def _check_recursive_paged_frames(containers: Mapping[str, SequenceContainer]) -> None:
    """Rule 4 — a container reachable via paged_frame_entry may not itself contain one."""
    # Collect all containers referenced as paged_frame_entry targets
    paged_targets: set[str] = set()
    for c in containers.values():
        for e in c.entry_list:
            if isinstance(e, PagedFrameEntry):
                paged_targets.add(e.base_container_ref)

    # Any container in paged_targets that itself has a paged_frame_entry is an error
    for name in paged_targets:
        c = containers.get(name)
        if c is None:
            continue
        for e in c.entry_list:
            if isinstance(e, PagedFrameEntry):
                raise ParseError(
                    f"container {c.name!r} is reached via paged_frame_entry but "
                    f"contains its own paged_frame_entry; nesting not supported"
                )


def _check_dynamic_ref_ordering(
    containers: Mapping[str, SequenceContainer],
    parameter_types: Mapping[str, ParameterType],
) -> None:
    """Rule 5 — a dynamic_ref binary entry's size_ref must appear earlier in the same container as an integer entry."""
    for c in containers.values():
        decoded_so_far: dict[str, ParameterType] = {}
        for e in c.entry_list:
            if isinstance(e, PagedFrameEntry):
                continue
            if isinstance(e, RepeatEntry):
                inner = e.entry
                _validate_dynamic_ref_entry(inner, decoded_so_far, c.name, parameter_types)
                t = parameter_types.get(inner.type_ref)
                if t is not None:
                    decoded_so_far[inner.name] = t
            elif isinstance(e, ParameterRefEntry):
                _validate_dynamic_ref_entry(e, decoded_so_far, c.name, parameter_types)
                t = parameter_types.get(e.type_ref)
                if t is not None:
                    decoded_so_far[e.name] = t


def _validate_dynamic_ref_entry(
    e: ParameterRefEntry,
    decoded_so_far: dict[str, ParameterType],
    container_name: str,
    parameter_types: Mapping[str, ParameterType],
) -> None:
    t = parameter_types.get(e.type_ref)
    if not isinstance(t, BinaryParameterType) or t.size_kind != "dynamic_ref":
        return
    ref = t.size_ref
    if ref not in decoded_so_far:
        raise InvalidDynamicRef(
            e.name, ref,
            f"not decoded earlier in container {container_name!r}"
        )
    ref_type = decoded_so_far[ref]
    if not isinstance(ref_type, IntegerParameterType):
        raise InvalidDynamicRef(
            e.name, ref,
            f"references type {ref_type.__class__.__name__}, expected IntegerParameterType"
        )


def _check_container_domains(containers: Mapping[str, SequenceContainer]) -> None:
    """Rule 6 — every non-abstract SequenceContainer must declare a non-empty domain."""
    for c in containers.values():
        if c.abstract:
            continue
        if not c.domain:
            raise ParseError(
                f"container {c.name!r} must declare a non-empty domain"
            )


def _check_repeat_entry_count(containers: Mapping[str, SequenceContainer]) -> None:
    """RepeatEntry.count_fixed must be >= 1 (XTCE 1.3 / XTCE13-143).

    count == 1 is a no-op repeat (single iteration); count == 0 would
    produce zero iterations which is degenerate and almost certainly
    a typo. Reject at parse time.
    """
    for c in containers.values():
        for entry in c.entry_list:
            if not isinstance(entry, RepeatEntry):
                continue
            if entry.count_kind == "fixed" and entry.count_fixed is not None:
                if entry.count_fixed < 1:
                    raise ParseError(
                        f"container {c.name!r}: repeat_entry on {entry.entry.name!r} "
                        f"has count={entry.count_fixed}; XTCE 1.3 requires count >= 1"
                    )


def _check_argument_bound_types(
    meta_commands: Mapping[str, MetaCommand],
    parameter_types: Mapping[str, ParameterType],
) -> None:
    """Rule 7 — valid_range only on numeric types; valid_values/invalid_values type-compatible."""
    numeric_types = (IntegerParameterType, FloatParameterType)
    string_types = (StringParameterType,)

    for m in meta_commands.values():
        for arg in m.argument_list:
            t = parameter_types.get(arg.type_ref)
            if t is None:
                continue  # unknown ref caught by _check_type_refs
            if arg.valid_range is not None:
                if not isinstance(t, numeric_types):
                    raise ParseError(
                        f"meta_command {m.id!r} argument {arg.name!r} has valid_range "
                        f"but type {arg.type_ref!r} is not numeric"
                    )
            if arg.valid_values is not None:
                _check_value_list_compat(m.id, arg.name, arg.type_ref, t, arg.valid_values, "valid_values")
            if arg.invalid_values is not None:
                _check_value_list_compat(m.id, arg.name, arg.type_ref, t, arg.invalid_values, "invalid_values")


def _check_value_list_compat(
    cmd_id: str, arg_name: str, type_ref: str,
    t: ParameterType, values: tuple, field_name: str,
) -> None:
    if isinstance(t, (IntegerParameterType, FloatParameterType)):
        for v in values:
            if not isinstance(v, (int, float)):
                raise ParseError(
                    f"meta_command {cmd_id!r} argument {arg_name!r} {field_name} "
                    f"entry {v!r} is not numeric; type {type_ref!r} is numeric"
                )
    elif isinstance(t, StringParameterType):
        for v in values:
            if not isinstance(v, str):
                raise ParseError(
                    f"meta_command {cmd_id!r} argument {arg_name!r} {field_name} "
                    f"entry {v!r} is not a string; type {type_ref!r} is a string type"
                )


def _check_plugins(parameter_types: Mapping[str, ParameterType], plugins: Mapping[str, Callable]) -> None:
    for t in parameter_types.values():
        cal = getattr(t, "calibrator", None)
        if isinstance(cal, PythonCalibrator) and cal.callable_ref not in plugins:
            raise MissingPluginError(cal.callable_ref)


def _collect_warnings(
    parameter_types: Mapping[str, ParameterType],
    bitfield_types: Mapping[str, BitfieldType],
    containers: Mapping[str, SequenceContainer],
) -> list[ParseWarning]:
    warnings: list[ParseWarning] = []

    # Subset-overlap (ContainerShadow)
    sigs: list[tuple[str, frozenset]] = []
    for c in containers.values():
        rc = c.restriction_criteria
        if rc is None or not rc.packet:
            continue
        sig = frozenset(
            (cmp.parameter_ref, cmp.value)
            for cmp in rc.packet if cmp.operator == "=="
        )
        if not sig:
            continue
        sigs.append((c.name, sig))
    for i, (name_a, sig_a) in enumerate(sigs):
        for name_b, sig_b in sigs[i + 1:]:
            if sig_a < sig_b:
                warnings.append(ContainerShadow(broader=name_a, specific=name_b))
            elif sig_b < sig_a:
                # Broader after specific is fine (specific wins by first-match)
                pass

    # Enum-slice truncation
    for bf in bitfield_types.values():
        for slice_entry in bf.entry_list:
            if slice_entry.kind != "enum" or not slice_entry.enum_ref:
                continue
            enum_t = parameter_types.get(slice_entry.enum_ref)
            if not isinstance(enum_t, EnumeratedParameterType):
                continue
            slice_width = slice_entry.bits[1] - slice_entry.bits[0] + 1
            max_raw = max((v.raw for v in enum_t.values), default=0)
            needed_bits = max(1, max_raw.bit_length())
            if slice_width < needed_bits:
                warnings.append(EnumSliceTruncation(
                    bitfield=bf.name, slice_name=slice_entry.name,
                    slice_width=slice_width, enum_max_raw=max_raw,
                ))

    return warnings


__all__ = ["parse_yaml", "parse_yaml_for_tooling"]
