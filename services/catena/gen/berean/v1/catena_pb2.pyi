from berean.v1 import answer_pb2 as _answer_pb2
from berean.v1 import filter_pb2 as _filter_pb2
from berean.v1 import trace_pb2 as _trace_pb2
from berean.v1 import verification_pb2 as _verification_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GenerationFailureCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GENERATION_FAILURE_CODE_UNSPECIFIED: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_TRUNCATED: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_CONTEXT_EXHAUSTED: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_NOT_JSON: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_NOT_AN_OBJECT: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_EMPTY: _ClassVar[GenerationFailureCode]
    GENERATION_FAILURE_CODE_PROVIDER_REFUSED: _ClassVar[GenerationFailureCode]
GENERATION_FAILURE_CODE_UNSPECIFIED: GenerationFailureCode
GENERATION_FAILURE_CODE_TRUNCATED: GenerationFailureCode
GENERATION_FAILURE_CODE_CONTEXT_EXHAUSTED: GenerationFailureCode
GENERATION_FAILURE_CODE_NOT_JSON: GenerationFailureCode
GENERATION_FAILURE_CODE_NOT_AN_OBJECT: GenerationFailureCode
GENERATION_FAILURE_CODE_EMPTY: GenerationFailureCode
GENERATION_FAILURE_CODE_PROVIDER_REFUSED: GenerationFailureCode

class AnswerRequest(_message.Message):
    __slots__ = ()
    QUERY_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    FILTER_SPEC_FIELD_NUMBER: _ClassVar[int]
    CONTESTED_LOCI_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_FAILURES_FIELD_NUMBER: _ClassVar[int]
    ANSWER_FAILURES_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    query: str
    conversation_context: _containers.RepeatedCompositeFieldContainer[ConversationTurn]
    filter_spec: _filter_pb2.FilterSpec
    contested_loci: _containers.RepeatedCompositeFieldContainer[_filter_pb2.ContestedLocus]
    request_id: str
    previous_failures: _containers.RepeatedCompositeFieldContainer[_verification_pb2.VerificationResult]
    answer_failures: _containers.RepeatedCompositeFieldContainer[_verification_pb2.AnswerFailure]
    attempt: int
    def __init__(self, query: _Optional[str] = ..., conversation_context: _Optional[_Iterable[_Union[ConversationTurn, _Mapping]]] = ..., filter_spec: _Optional[_Union[_filter_pb2.FilterSpec, _Mapping]] = ..., contested_loci: _Optional[_Iterable[_Union[_filter_pb2.ContestedLocus, _Mapping]]] = ..., request_id: _Optional[str] = ..., previous_failures: _Optional[_Iterable[_Union[_verification_pb2.VerificationResult, _Mapping]]] = ..., answer_failures: _Optional[_Iterable[_Union[_verification_pb2.AnswerFailure, _Mapping]]] = ..., attempt: _Optional[int] = ...) -> None: ...

class ConversationTurn(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AnswerResponse(_message.Message):
    __slots__ = ()
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FAILURE_FIELD_NUMBER: _ClassVar[int]
    TRACE_FIELD_NUMBER: _ClassVar[int]
    answer: _answer_pb2.AnswerObject
    generation_failure: GenerationFailure
    trace: _trace_pb2.RetrievalTrace
    def __init__(self, answer: _Optional[_Union[_answer_pb2.AnswerObject, _Mapping]] = ..., generation_failure: _Optional[_Union[GenerationFailure, _Mapping]] = ..., trace: _Optional[_Union[_trace_pb2.RetrievalTrace, _Mapping]] = ...) -> None: ...

class GenerationFailure(_message.Message):
    __slots__ = ()
    CODE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    code: GenerationFailureCode
    detail: str
    completion_tokens: int
    def __init__(self, code: _Optional[_Union[GenerationFailureCode, str]] = ..., detail: _Optional[str] = ..., completion_tokens: _Optional[int] = ...) -> None: ...
