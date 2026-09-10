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
OVERALL_RESULT_UNSPECIFIED: OverallResult
OVERALL_RESULT_VERIFIED: OverallResult
OVERALL_RESULT_REGENERATED: OverallResult
OVERALL_RESULT_DEGRADED: OverallResult

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
