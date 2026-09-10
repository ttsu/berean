from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RetrievalTrace(_message.Message):
    __slots__ = ()
    REWRITTEN_QUERY_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_MODEL_FIELD_NUMBER: _ClassVar[int]
    DIM_FIELD_NUMBER: _ClassVar[int]
    GENERATION_MODEL_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    TIMINGS_FIELD_NUMBER: _ClassVar[int]
    rewritten_query: str
    candidates: _containers.RepeatedCompositeFieldContainer[Candidate]
    embedding_model: str
    dim: int
    generation_model: str
    top_k: int
    timings: Timings
    def __init__(self, rewritten_query: _Optional[str] = ..., candidates: _Optional[_Iterable[_Union[Candidate, _Mapping]]] = ..., embedding_model: _Optional[str] = ..., dim: _Optional[int] = ..., generation_model: _Optional[str] = ..., top_k: _Optional[int] = ..., timings: _Optional[_Union[Timings, _Mapping]] = ...) -> None: ...

class Candidate(_message.Message):
    __slots__ = ()
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    INCLUDED_FIELD_NUMBER: _ClassVar[int]
    EXCLUSION_REASON_FIELD_NUMBER: _ClassVar[int]
    corpus_id: str
    locator: str
    score: float
    included: bool
    exclusion_reason: str
    def __init__(self, corpus_id: _Optional[str] = ..., locator: _Optional[str] = ..., score: _Optional[float] = ..., included: _Optional[bool] = ..., exclusion_reason: _Optional[str] = ...) -> None: ...

class Timings(_message.Message):
    __slots__ = ()
    EMBED_MS_FIELD_NUMBER: _ClassVar[int]
    SEARCH_MS_FIELD_NUMBER: _ClassVar[int]
    GENERATE_MS_FIELD_NUMBER: _ClassVar[int]
    embed_ms: int
    search_ms: int
    generate_ms: int
    def __init__(self, embed_ms: _Optional[int] = ..., search_ms: _Optional[int] = ..., generate_ms: _Optional[int] = ...) -> None: ...
