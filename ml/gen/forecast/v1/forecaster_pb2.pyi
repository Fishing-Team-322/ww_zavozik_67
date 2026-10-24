from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DailyFlow(_message.Message):
    __slots__ = ("date", "inflow", "outflow", "missing", "by_category")
    class ByCategoryEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    DATE_FIELD_NUMBER: _ClassVar[int]
    INFLOW_FIELD_NUMBER: _ClassVar[int]
    OUTFLOW_FIELD_NUMBER: _ClassVar[int]
    MISSING_FIELD_NUMBER: _ClassVar[int]
    BY_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    date: str
    inflow: float
    outflow: float
    missing: bool
    by_category: _containers.ScalarMap[str, float]
    def __init__(self, date: _Optional[str] = ..., inflow: _Optional[float] = ..., outflow: _Optional[float] = ..., missing: _Optional[bool] = ..., by_category: _Optional[_Mapping[str, float]] = ...) -> None: ...

class ForecastRequest(_message.Message):
    __slots__ = ("model", "company_id", "industry", "history", "horizon_days", "n_paths", "seed", "flow_scope")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    COMPANY_ID_FIELD_NUMBER: _ClassVar[int]
    INDUSTRY_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    HORIZON_DAYS_FIELD_NUMBER: _ClassVar[int]
    N_PATHS_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    FLOW_SCOPE_FIELD_NUMBER: _ClassVar[int]
    model: str
    company_id: str
    industry: str
    history: _containers.RepeatedCompositeFieldContainer[DailyFlow]
    horizon_days: int
    n_paths: int
    seed: int
    flow_scope: str
    def __init__(self, model: _Optional[str] = ..., company_id: _Optional[str] = ..., industry: _Optional[str] = ..., history: _Optional[_Iterable[_Union[DailyFlow, _Mapping]]] = ..., horizon_days: _Optional[int] = ..., n_paths: _Optional[int] = ..., seed: _Optional[int] = ..., flow_scope: _Optional[str] = ...) -> None: ...

class Path(_message.Message):
    __slots__ = ("inflow", "outflow")
    INFLOW_FIELD_NUMBER: _ClassVar[int]
    OUTFLOW_FIELD_NUMBER: _ClassVar[int]
    inflow: _containers.RepeatedScalarFieldContainer[float]
    outflow: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, inflow: _Optional[_Iterable[float]] = ..., outflow: _Optional[_Iterable[float]] = ...) -> None: ...

class NetQuantiles(_message.Message):
    __slots__ = ("date", "p10", "p50", "p90")
    DATE_FIELD_NUMBER: _ClassVar[int]
    P10_FIELD_NUMBER: _ClassVar[int]
    P50_FIELD_NUMBER: _ClassVar[int]
    P90_FIELD_NUMBER: _ClassVar[int]
    date: str
    p10: float
    p50: float
    p90: float
    def __init__(self, date: _Optional[str] = ..., p10: _Optional[float] = ..., p50: _Optional[float] = ..., p90: _Optional[float] = ...) -> None: ...

class ForecastResponse(_message.Message):
    __slots__ = ("model_used", "dates", "paths", "net_quantiles", "low_confidence", "model_version", "flow_scope", "warnings", "fallback_used")
    MODEL_USED_FIELD_NUMBER: _ClassVar[int]
    DATES_FIELD_NUMBER: _ClassVar[int]
    PATHS_FIELD_NUMBER: _ClassVar[int]
    NET_QUANTILES_FIELD_NUMBER: _ClassVar[int]
    LOW_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    MODEL_VERSION_FIELD_NUMBER: _ClassVar[int]
    FLOW_SCOPE_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    FALLBACK_USED_FIELD_NUMBER: _ClassVar[int]
    model_used: str
    dates: _containers.RepeatedScalarFieldContainer[str]
    paths: _containers.RepeatedCompositeFieldContainer[Path]
    net_quantiles: _containers.RepeatedCompositeFieldContainer[NetQuantiles]
    low_confidence: bool
    model_version: str
    flow_scope: str
    warnings: _containers.RepeatedScalarFieldContainer[str]
    fallback_used: bool
    def __init__(self, model_used: _Optional[str] = ..., dates: _Optional[_Iterable[str]] = ..., paths: _Optional[_Iterable[_Union[Path, _Mapping]]] = ..., net_quantiles: _Optional[_Iterable[_Union[NetQuantiles, _Mapping]]] = ..., low_confidence: _Optional[bool] = ..., model_version: _Optional[str] = ..., flow_scope: _Optional[str] = ..., warnings: _Optional[_Iterable[str]] = ..., fallback_used: _Optional[bool] = ...) -> None: ...

class ListModelsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ModelInfo(_message.Message):
    __slots__ = ("name", "description", "is_default")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    IS_DEFAULT_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    is_default: bool
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., is_default: _Optional[bool] = ...) -> None: ...

class ListModelsResponse(_message.Message):
    __slots__ = ("models",)
    MODELS_FIELD_NUMBER: _ClassVar[int]
    models: _containers.RepeatedCompositeFieldContainer[ModelInfo]
    def __init__(self, models: _Optional[_Iterable[_Union[ModelInfo, _Mapping]]] = ...) -> None: ...
