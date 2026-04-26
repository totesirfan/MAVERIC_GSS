"""Declarative mission-database runtime — see docs/superpowers/specs/2026-04-24-declarative-telemetry-design.md.

Public re-exports.

Author:  Irfan Annuar - USC ISI SERC
"""

from .bitfield import BitfieldEntry, BitfieldType
from .calibrators import Calibrator, PolynomialCalibrator, PythonCalibrator
from .calibrator_runtime import CalibratorRuntime, PluginCallable
from .command_ops import (
    DeclarativeCommandOpsAdapter,
    build_declarative_command_ops,
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
from .cursor import BitCursor, TokenCursor
from .errors import (
    ArgsTooLong,
    CmdIdTooLong,
    ContainerConflict,
    CrcMismatch,
    DuplicateTypeName,
    HeaderFieldNotOverridable,
    HeaderValueNotAllowed,
    IncompatibleSchemaVersion,
    InvalidDynamicRef,
    MissingPluginError,
    MissingRequiredHeaderField,
    NonJsonSafeArg,
    PagedFrameTargetEmpty,
    ParseError,
    SpecError,
    SpecRuntimeError,
    UnknownHeaderValue,
    UnknownTypeRef,
    UnknownVerifierId,
)
from .mission import (
    ContainerShadow,
    EnumSliceTruncation,
    Mission,
    MissionHeader,
    ParseWarning,
)
from .packet_codec import CommandHeader, PacketCodec
from .parameters import Parameter
from .parameter_types import (
    BUILT_IN_PARAMETER_TYPES,
    AbsoluteTimeParameterType,
    AggregateMember,
    AggregateParameterType,
    ArrayParameterType,
    BinaryParameterType,
    EnumeratedParameterType,
    EnumValue,
    FloatParameterType,
    IntegerParameterType,
    ParameterType,
    ParameterTypeKind,
    StringParameterType,
)
from .runtime import (
    BitfieldDecoder,
    CommandEncoder,
    ContainerMatcher,
    DeclarativeWalker,
    EntryDecoder,
    TypeCodec,
)
from .time_codec import decode_millis_u64, encode_millis_u64
from .types import ByteOrder, HeaderValue
from .walker_packet import WalkerPacket
from .verifier_decls import VerifierRules, VerifierSpecDecl, VerifierStage, VerifierTone
from .verifier_runtime import derive_verifier_set
from .yaml_parse import parse_yaml, parse_yaml_for_tooling
from .yaml_schema import MissionDocument

from mav_gss_lib.platform.spec.framing import (
    FramerSpec,
    FramingSpec,
    parse_framing_section,
)


__all__ = [
    # Types
    "ByteOrder", "HeaderValue",
    # Calibrators
    "Calibrator", "PolynomialCalibrator", "PythonCalibrator",
    "CalibratorRuntime", "PluginCallable",
    # Parameter types
    "ParameterType", "ParameterTypeKind", "BUILT_IN_PARAMETER_TYPES",
    "IntegerParameterType", "FloatParameterType", "StringParameterType",
    "BinaryParameterType", "EnumeratedParameterType", "EnumValue",
    "AbsoluteTimeParameterType", "AggregateMember", "AggregateParameterType",
    "ArrayParameterType",
    # Bitfields
    "BitfieldEntry", "BitfieldType",
    # Parameters
    "Parameter",
    # Containers
    "Comparison", "RestrictionCriteria", "ParameterRefEntry",
    "RepeatEntry", "PagedFrameEntry", "Entry", "SequenceContainer",
    # Commands
    "Argument", "MetaCommand",
    # Mission
    "MissionHeader", "Mission", "ParseWarning",
    "ContainerShadow", "EnumSliceTruncation",
    # Walker substrate
    "WalkerPacket", "CommandHeader", "PacketCodec",
    "BitCursor", "TokenCursor",
    # Time codec
    "encode_millis_u64", "decode_millis_u64",
    # Runtime
    "TypeCodec", "ContainerMatcher", "BitfieldDecoder",
    "EntryDecoder", "CommandEncoder", "DeclarativeWalker",
    # Factories
    "build_declarative_command_ops", "DeclarativeCommandOpsAdapter",
    # Verifiers
    "VerifierSpecDecl", "VerifierRules", "VerifierStage", "VerifierTone",
    "derive_verifier_set",
    # YAML
    "MissionDocument", "parse_yaml", "parse_yaml_for_tooling",
    # Framing spec
    "FramerSpec", "FramingSpec", "parse_framing_section",
    # Errors
    "SpecError", "ParseError", "SpecRuntimeError",
    "UnknownTypeRef", "DuplicateTypeName", "ContainerConflict",
    "IncompatibleSchemaVersion", "InvalidDynamicRef",
    "PagedFrameTargetEmpty", "MissingPluginError",
    "MissingRequiredHeaderField", "HeaderFieldNotOverridable",
    "HeaderValueNotAllowed", "UnknownHeaderValue",
    "ArgsTooLong", "CmdIdTooLong", "CrcMismatch", "NonJsonSafeArg",
    "UnknownVerifierId",
]
