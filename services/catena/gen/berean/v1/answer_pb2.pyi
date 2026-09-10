from berean.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ConfidenceLevel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONFIDENCE_LEVEL_UNSPECIFIED: _ClassVar[ConfidenceLevel]
    CONFIDENCE_LEVEL_HIGH: _ClassVar[ConfidenceLevel]
    CONFIDENCE_LEVEL_MEDIUM: _ClassVar[ConfidenceLevel]
    CONFIDENCE_LEVEL_LOW: _ClassVar[ConfidenceLevel]
CONFIDENCE_LEVEL_UNSPECIFIED: ConfidenceLevel
CONFIDENCE_LEVEL_HIGH: ConfidenceLevel
CONFIDENCE_LEVEL_MEDIUM: ConfidenceLevel
CONFIDENCE_LEVEL_LOW: ConfidenceLevel

class AnswerObject(_message.Message):
    __slots__ = ()
    POSITION_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTIONS_FIELD_NUMBER: _ClassVar[int]
    CONTRARY_POSITIONS_FIELD_NUMBER: _ClassVar[int]
    CONTESTED_FIELD_NUMBER: _ClassVar[int]
    NO_ANSWER_REASON_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    position: str
    arguments: _containers.RepeatedCompositeFieldContainer[Argument]
    descriptions: _containers.RepeatedCompositeFieldContainer[Description]
    contrary_positions: _containers.RepeatedCompositeFieldContainer[ContraryPosition]
    contested: Contested
    no_answer_reason: str
    confidence: Confidence
    def __init__(self, position: _Optional[str] = ..., arguments: _Optional[_Iterable[_Union[Argument, _Mapping]]] = ..., descriptions: _Optional[_Iterable[_Union[Description, _Mapping]]] = ..., contrary_positions: _Optional[_Iterable[_Union[ContraryPosition, _Mapping]]] = ..., contested: _Optional[_Union[Contested, _Mapping]] = ..., no_answer_reason: _Optional[str] = ..., confidence: _Optional[_Union[Confidence, _Mapping]] = ...) -> None: ...

class Argument(_message.Message):
    __slots__ = ()
    CLAIM_FIELD_NUMBER: _ClassVar[int]
    WARRANT_FIELD_NUMBER: _ClassVar[int]
    CITATIONS_FIELD_NUMBER: _ClassVar[int]
    claim: str
    warrant: str
    citations: _containers.RepeatedCompositeFieldContainer[Citation]
    def __init__(self, claim: _Optional[str] = ..., warrant: _Optional[str] = ..., citations: _Optional[_Iterable[_Union[Citation, _Mapping]]] = ...) -> None: ...

class Description(_message.Message):
    __slots__ = ()
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    CITATIONS_FIELD_NUMBER: _ClassVar[int]
    subject: str
    content: str
    citations: _containers.RepeatedCompositeFieldContainer[Citation]
    def __init__(self, subject: _Optional[str] = ..., content: _Optional[str] = ..., citations: _Optional[_Iterable[_Union[Citation, _Mapping]]] = ...) -> None: ...

class ContraryPosition(_message.Message):
    __slots__ = ()
    POSITION_FIELD_NUMBER: _ClassVar[int]
    HELD_BY_FIELD_NUMBER: _ClassVar[int]
    CITATIONS_FIELD_NUMBER: _ClassVar[int]
    position: str
    held_by: _containers.RepeatedScalarFieldContainer[str]
    citations: _containers.RepeatedCompositeFieldContainer[Citation]
    def __init__(self, position: _Optional[str] = ..., held_by: _Optional[_Iterable[str]] = ..., citations: _Optional[_Iterable[_Union[Citation, _Mapping]]] = ...) -> None: ...

class Contested(_message.Message):
    __slots__ = ()
    IS_CONTESTED_FIELD_NUMBER: _ClassVar[int]
    LOCUS_FIELD_NUMBER: _ClassVar[int]
    CITATIONS_FIELD_NUMBER: _ClassVar[int]
    STATE_OF_DEBATE_FIELD_NUMBER: _ClassVar[int]
    is_contested: bool
    locus: str
    citations: _containers.RepeatedCompositeFieldContainer[Citation]
    state_of_debate: str
    def __init__(self, is_contested: _Optional[bool] = ..., locus: _Optional[str] = ..., citations: _Optional[_Iterable[_Union[Citation, _Mapping]]] = ..., state_of_debate: _Optional[str] = ...) -> None: ...

class Citation(_message.Message):
    __slots__ = ()
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    QUOTE_FIELD_NUMBER: _ClassVar[int]
    corpus_id: str
    locator: str
    tier: _common_pb2.Tier
    quote: str
    def __init__(self, corpus_id: _Optional[str] = ..., locator: _Optional[str] = ..., tier: _Optional[_Union[_common_pb2.Tier, str]] = ..., quote: _Optional[str] = ...) -> None: ...

class Confidence(_message.Message):
    __slots__ = ()
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    level: ConfidenceLevel
    reason: str
    def __init__(self, level: _Optional[_Union[ConfidenceLevel, str]] = ..., reason: _Optional[str] = ...) -> None: ...
