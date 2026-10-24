from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Operation(_message.Message):
    __slots__ = ("id", "direction", "payment_purpose", "counterparty_name")
    ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_PURPOSE_FIELD_NUMBER: _ClassVar[int]
    COUNTERPARTY_NAME_FIELD_NUMBER: _ClassVar[int]
    id: str
    direction: str
    payment_purpose: str
    counterparty_name: str
    def __init__(self, id: _Optional[str] = ..., direction: _Optional[str] = ..., payment_purpose: _Optional[str] = ..., counterparty_name: _Optional[str] = ...) -> None: ...

class AssignRequest(_message.Message):
    __slots__ = ("operations",)
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    operations: _containers.RepeatedCompositeFieldContainer[Operation]
    def __init__(self, operations: _Optional[_Iterable[_Union[Operation, _Mapping]]] = ...) -> None: ...

class Candidate(_message.Message):
    __slots__ = ("category_id", "title", "similarity")
    CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SIMILARITY_FIELD_NUMBER: _ClassVar[int]
    category_id: str
    title: str
    similarity: float
    def __init__(self, category_id: _Optional[str] = ..., title: _Optional[str] = ..., similarity: _Optional[float] = ...) -> None: ...

class Assignment(_message.Message):
    __slots__ = ("id", "embedding", "category_id", "category_title", "status", "candidates", "similarity", "margin", "channel", "tags", "auxiliary_source", "category_path", "coarse_category_id", "coarse_category_title")
    ID_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_TITLE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    SIMILARITY_FIELD_NUMBER: _ClassVar[int]
    MARGIN_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    AUXILIARY_SOURCE_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_PATH_FIELD_NUMBER: _ClassVar[int]
    COARSE_CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    COARSE_CATEGORY_TITLE_FIELD_NUMBER: _ClassVar[int]
    id: str
    embedding: _containers.RepeatedScalarFieldContainer[float]
    category_id: str
    category_title: str
    status: str
    candidates: _containers.RepeatedCompositeFieldContainer[Candidate]
    similarity: float
    margin: float
    channel: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    auxiliary_source: str
    category_path: _containers.RepeatedScalarFieldContainer[str]
    coarse_category_id: str
    coarse_category_title: str
    def __init__(self, id: _Optional[str] = ..., embedding: _Optional[_Iterable[float]] = ..., category_id: _Optional[str] = ..., category_title: _Optional[str] = ..., status: _Optional[str] = ..., candidates: _Optional[_Iterable[_Union[Candidate, _Mapping]]] = ..., similarity: _Optional[float] = ..., margin: _Optional[float] = ..., channel: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., auxiliary_source: _Optional[str] = ..., category_path: _Optional[_Iterable[str]] = ..., coarse_category_id: _Optional[str] = ..., coarse_category_title: _Optional[str] = ...) -> None: ...

class AssignResponse(_message.Message):
    __slots__ = ("results", "encoder_version", "taxonomy_version", "embedding_dim", "score_kind", "hierarchy_version")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    ENCODER_VERSION_FIELD_NUMBER: _ClassVar[int]
    TAXONOMY_VERSION_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_DIM_FIELD_NUMBER: _ClassVar[int]
    SCORE_KIND_FIELD_NUMBER: _ClassVar[int]
    HIERARCHY_VERSION_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[Assignment]
    encoder_version: str
    taxonomy_version: str
    embedding_dim: int
    score_kind: str
    hierarchy_version: str
    def __init__(self, results: _Optional[_Iterable[_Union[Assignment, _Mapping]]] = ..., encoder_version: _Optional[str] = ..., taxonomy_version: _Optional[str] = ..., embedding_dim: _Optional[int] = ..., score_kind: _Optional[str] = ..., hierarchy_version: _Optional[str] = ...) -> None: ...

class Category(_message.Message):
    __slots__ = ("id", "title", "title_status", "direction", "independent_families", "companies", "attributes_status", "parent_id", "node_kind", "coarse_level")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    TITLE_STATUS_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    INDEPENDENT_FAMILIES_FIELD_NUMBER: _ClassVar[int]
    COMPANIES_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_STATUS_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_KIND_FIELD_NUMBER: _ClassVar[int]
    COARSE_LEVEL_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    title_status: str
    direction: str
    independent_families: int
    companies: int
    attributes_status: str
    parent_id: str
    node_kind: str
    coarse_level: bool
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., title_status: _Optional[str] = ..., direction: _Optional[str] = ..., independent_families: _Optional[int] = ..., companies: _Optional[int] = ..., attributes_status: _Optional[str] = ..., parent_id: _Optional[str] = ..., node_kind: _Optional[str] = ..., coarse_level: _Optional[bool] = ...) -> None: ...

class GetTaxonomyRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetTaxonomyResponse(_message.Message):
    __slots__ = ("categories", "encoder_version", "taxonomy_version", "hierarchy_version")
    CATEGORIES_FIELD_NUMBER: _ClassVar[int]
    ENCODER_VERSION_FIELD_NUMBER: _ClassVar[int]
    TAXONOMY_VERSION_FIELD_NUMBER: _ClassVar[int]
    HIERARCHY_VERSION_FIELD_NUMBER: _ClassVar[int]
    categories: _containers.RepeatedCompositeFieldContainer[Category]
    encoder_version: str
    taxonomy_version: str
    hierarchy_version: str
    def __init__(self, categories: _Optional[_Iterable[_Union[Category, _Mapping]]] = ..., encoder_version: _Optional[str] = ..., taxonomy_version: _Optional[str] = ..., hierarchy_version: _Optional[str] = ...) -> None: ...
