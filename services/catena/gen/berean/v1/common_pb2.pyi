from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Tier(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TIER_UNSPECIFIED: _ClassVar[Tier]
    TIER_BINDING: _ClassVar[Tier]
    TIER_GOVERNING: _ClassVar[Tier]
    TIER_ADVISORY: _ClassVar[Tier]
    TIER_CONTRARY: _ClassVar[Tier]
    TIER_EXCLUDED: _ClassVar[Tier]
TIER_UNSPECIFIED: Tier
TIER_BINDING: Tier
TIER_GOVERNING: Tier
TIER_ADVISORY: Tier
TIER_CONTRARY: Tier
TIER_EXCLUDED: Tier

class CitationRef(_message.Message):
    __slots__ = ()
    CORPUS_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    corpus_id: str
    locator: str
    def __init__(self, corpus_id: _Optional[str] = ..., locator: _Optional[str] = ...) -> None: ...
