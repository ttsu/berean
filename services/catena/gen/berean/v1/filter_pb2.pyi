from berean.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FilterSpec(_message.Message):
    __slots__ = ()
    CORPORA_FIELD_NUMBER: _ClassVar[int]
    TIER_WEIGHTS_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    corpora: _containers.RepeatedCompositeFieldContainer[CorpusFilter]
    tier_weights: _containers.RepeatedCompositeFieldContainer[TierWeight]
    top_k: int
    def __init__(self, corpora: _Optional[_Iterable[_Union[CorpusFilter, _Mapping]]] = ..., tier_weights: _Optional[_Iterable[_Union[TierWeight, _Mapping]]] = ..., top_k: _Optional[int] = ...) -> None: ...

class CorpusFilter(_message.Message):
    __slots__ = ()
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    corpus_id: str
    tier: _common_pb2.Tier
    def __init__(self, corpus_id: _Optional[str] = ..., tier: _Optional[_Union[_common_pb2.Tier, str]] = ...) -> None: ...

class TierWeight(_message.Message):
    __slots__ = ()
    TIER_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    tier: _common_pb2.Tier
    weight: float
    def __init__(self, tier: _Optional[_Union[_common_pb2.Tier, str]] = ..., weight: _Optional[float] = ...) -> None: ...

class ContestedLocus(_message.Message):
    __slots__ = ()
    LOCUS_FIELD_NUMBER: _ClassVar[int]
    RULING_FIELD_NUMBER: _ClassVar[int]
    locus: str
    ruling: _common_pb2.CitationRef
    def __init__(self, locus: _Optional[str] = ..., ruling: _Optional[_Union[_common_pb2.CitationRef, _Mapping]] = ...) -> None: ...
