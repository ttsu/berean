from berean.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OverallResult(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OVERALL_RESULT_UNSPECIFIED: _ClassVar[OverallResult]
    OVERALL_RESULT_VERIFIED: _ClassVar[OverallResult]
    OVERALL_RESULT_REGENERATED: _ClassVar[OverallResult]
    OVERALL_RESULT_DEGRADED: _ClassVar[OverallResult]

class AnswerFailureCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ANSWER_FAILURE_CODE_UNSPECIFIED: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_CITATIONS_REQUIRED: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_POSITION_WITHOUT_ARGUMENTS: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_CONTESTED_WITH_ARGUMENTS: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_CONTESTED_LOCUS_UNKNOWN: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_CONTESTED_RULING_UNCITED: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_CONTESTED_RULING_UNQUOTED: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_RULING_CITED_WHILE_UNCONTESTED: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_STATE_OF_DEBATE_WITHOUT_CONTEST: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_NO_ANSWER_REASON_NOT_ALONE: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_NO_ANSWER_REASON_TOO_LONG: _ClassVar[AnswerFailureCode]
    ANSWER_FAILURE_CODE_EMPTY_ANSWER: _ClassVar[AnswerFailureCode]
OVERALL_RESULT_UNSPECIFIED: OverallResult
OVERALL_RESULT_VERIFIED: OverallResult
OVERALL_RESULT_REGENERATED: OverallResult
OVERALL_RESULT_DEGRADED: OverallResult
ANSWER_FAILURE_CODE_UNSPECIFIED: AnswerFailureCode
ANSWER_FAILURE_CODE_CITATIONS_REQUIRED: AnswerFailureCode
ANSWER_FAILURE_CODE_ARGUMENT_LACKS_AUTHORITY: AnswerFailureCode
ANSWER_FAILURE_CODE_POSITION_WITHOUT_ARGUMENTS: AnswerFailureCode
ANSWER_FAILURE_CODE_CONTESTED_WITH_ARGUMENTS: AnswerFailureCode
ANSWER_FAILURE_CODE_CONTESTED_LOCUS_UNKNOWN: AnswerFailureCode
ANSWER_FAILURE_CODE_CONTESTED_RULING_UNCITED: AnswerFailureCode
ANSWER_FAILURE_CODE_CONTESTED_RULING_UNQUOTED: AnswerFailureCode
ANSWER_FAILURE_CODE_RULING_CITED_WHILE_UNCONTESTED: AnswerFailureCode
ANSWER_FAILURE_CODE_STATE_OF_DEBATE_WITHOUT_CONTEST: AnswerFailureCode
ANSWER_FAILURE_CODE_NO_ANSWER_REASON_NOT_ALONE: AnswerFailureCode
ANSWER_FAILURE_CODE_NO_ANSWER_REASON_TOO_LONG: AnswerFailureCode
ANSWER_FAILURE_CODE_EMPTY_ANSWER: AnswerFailureCode

class VerificationResult(_message.Message):
    __slots__ = ()
    CITATION_REF_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_RESOLVED_FIELD_NUMBER: _ClassVar[int]
    QUOTE_MATCHED_FIELD_NUMBER: _ClassVar[int]
    TIER_PERMITTED_FIELD_NUMBER: _ClassVar[int]
    LICENSE_PERMITTED_FIELD_NUMBER: _ClassVar[int]
    FAILURE_DETAIL_FIELD_NUMBER: _ClassVar[int]
    citation_ref: _common_pb2.CitationRef
    locator_resolved: bool
    quote_matched: bool
    tier_permitted: bool
    license_permitted: bool
    failure_detail: str
    def __init__(self, citation_ref: _Optional[_Union[_common_pb2.CitationRef, _Mapping]] = ..., locator_resolved: _Optional[bool] = ..., quote_matched: _Optional[bool] = ..., tier_permitted: _Optional[bool] = ..., license_permitted: _Optional[bool] = ..., failure_detail: _Optional[str] = ...) -> None: ...

class AnswerFailure(_message.Message):
    __slots__ = ()
    CODE_FIELD_NUMBER: _ClassVar[int]
    SLOT_FIELD_NUMBER: _ClassVar[int]
    CITATION_REF_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    code: AnswerFailureCode
    slot: str
    citation_ref: _common_pb2.CitationRef
    detail: str
    def __init__(self, code: _Optional[_Union[AnswerFailureCode, str]] = ..., slot: _Optional[str] = ..., citation_ref: _Optional[_Union[_common_pb2.CitationRef, _Mapping]] = ..., detail: _Optional[str] = ...) -> None: ...
