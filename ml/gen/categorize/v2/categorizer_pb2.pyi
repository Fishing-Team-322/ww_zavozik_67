from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Operation(_message.Message):
    __slots__ = ("id", "direction", "amount", "counterparty_type", "counterparty_name", "payment_purpose")
    ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    COUNTERPARTY_TYPE_FIELD_NUMBER: _ClassVar[int]
    COUNTERPARTY_NAME_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_PURPOSE_FIELD_NUMBER: _ClassVar[int]
    id: str
    direction: str
    amount: float
    counterparty_type: str
    counterparty_name: str
    payment_purpose: str
    def __init__(self, id: _Optional[str] = ..., direction: _Optional[str] = ..., amount: _Optional[float] = ..., counterparty_type: _Optional[str] = ..., counterparty_name: _Optional[str] = ..., payment_purpose: _Optional[str] = ...) -> None: ...

class ClassifyRequest(_message.Message):
    __slots__ = ("operations",)
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    operations: _containers.RepeatedCompositeFieldContainer[Operation]
    def __init__(self, operations: _Optional[_Iterable[_Union[Operation, _Mapping]]] = ...) -> None: ...

class Attributes(_message.Message):
    __slots__ = ("flow", "direction", "mandatory", "regular_hint")
    FLOW_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    MANDATORY_FIELD_NUMBER: _ClassVar[int]
    REGULAR_HINT_FIELD_NUMBER: _ClassVar[int]
    flow: str
    direction: str
    mandatory: bool
    regular_hint: bool
    def __init__(self, flow: _Optional[str] = ..., direction: _Optional[str] = ..., mandatory: _Optional[bool] = ..., regular_hint: _Optional[bool] = ...) -> None: ...

class Classification(_message.Message):
    __slots__ = ("id", "embedding", "category", "category_probs", "channel", "channel_probs", "tags", "tag_probs", "attributes", "novelty", "is_novel", "taxonomy_version", "model_version")
    class CategoryProbsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class ChannelProbsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class TagProbsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    ID_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_PROBS_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_PROBS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    TAG_PROBS_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    NOVELTY_FIELD_NUMBER: _ClassVar[int]
    IS_NOVEL_FIELD_NUMBER: _ClassVar[int]
    TAXONOMY_VERSION_FIELD_NUMBER: _ClassVar[int]
    MODEL_VERSION_FIELD_NUMBER: _ClassVar[int]
    id: str
    embedding: _containers.RepeatedScalarFieldContainer[float]
    category: str
    category_probs: _containers.ScalarMap[str, float]
    channel: str
    channel_probs: _containers.ScalarMap[str, float]
    tags: _containers.RepeatedScalarFieldContainer[str]
    tag_probs: _containers.ScalarMap[str, float]
    attributes: Attributes
    novelty: float
    is_novel: bool
    taxonomy_version: str
    model_version: str
    def __init__(self, id: _Optional[str] = ..., embedding: _Optional[_Iterable[float]] = ..., category: _Optional[str] = ..., category_probs: _Optional[_Mapping[str, float]] = ..., channel: _Optional[str] = ..., channel_probs: _Optional[_Mapping[str, float]] = ..., tags: _Optional[_Iterable[str]] = ..., tag_probs: _Optional[_Mapping[str, float]] = ..., attributes: _Optional[_Union[Attributes, _Mapping]] = ..., novelty: _Optional[float] = ..., is_novel: _Optional[bool] = ..., taxonomy_version: _Optional[str] = ..., model_version: _Optional[str] = ...) -> None: ...

class ClassifyResponse(_message.Message):
    __slots__ = ("results", "model_version", "taxonomy_version", "embedding_dim")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    MODEL_VERSION_FIELD_NUMBER: _ClassVar[int]
    TAXONOMY_VERSION_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_DIM_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[Classification]
    model_version: str
    taxonomy_version: str
    embedding_dim: int
    def __init__(self, results: _Optional[_Iterable[_Union[Classification, _Mapping]]] = ..., model_version: _Optional[str] = ..., taxonomy_version: _Optional[str] = ..., embedding_dim: _Optional[int] = ...) -> None: ...
