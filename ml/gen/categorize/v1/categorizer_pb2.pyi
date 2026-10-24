from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Operation(_message.Message):
    __slots__ = ("id", "direction", "amount", "counterparty_inn", "counterparty_name", "payment_purpose")
    ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    COUNTERPARTY_INN_FIELD_NUMBER: _ClassVar[int]
    COUNTERPARTY_NAME_FIELD_NUMBER: _ClassVar[int]
    PAYMENT_PURPOSE_FIELD_NUMBER: _ClassVar[int]
    id: str
    direction: str
    amount: float
    counterparty_inn: str
    counterparty_name: str
    payment_purpose: str
    def __init__(self, id: _Optional[str] = ..., direction: _Optional[str] = ..., amount: _Optional[float] = ..., counterparty_inn: _Optional[str] = ..., counterparty_name: _Optional[str] = ..., payment_purpose: _Optional[str] = ...) -> None: ...

class ClassifyRequest(_message.Message):
    __slots__ = ("operations",)
    OPERATIONS_FIELD_NUMBER: _ClassVar[int]
    operations: _containers.RepeatedCompositeFieldContainer[Operation]
    def __init__(self, operations: _Optional[_Iterable[_Union[Operation, _Mapping]]] = ...) -> None: ...

class Classification(_message.Message):
    __slots__ = ("id", "category", "confidence")
    ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    id: str
    category: str
    confidence: float
    def __init__(self, id: _Optional[str] = ..., category: _Optional[str] = ..., confidence: _Optional[float] = ...) -> None: ...

class ClassifyResponse(_message.Message):
    __slots__ = ("results", "model_version")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    MODEL_VERSION_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[Classification]
    model_version: str
    def __init__(self, results: _Optional[_Iterable[_Union[Classification, _Mapping]]] = ..., model_version: _Optional[str] = ...) -> None: ...
