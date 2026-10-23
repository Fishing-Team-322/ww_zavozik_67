from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DailyFlow(_message.Message):
    __slots__ = ("date", "inflow", "outflow", "missing")
    DATE_FIELD_NUMBER: _ClassVar[int]
    INFLOW_FIELD_NUMBER: _ClassVar[int]
    OUTFLOW_FIELD_NUMBER: _ClassVar[int]
    MISSING_FIELD_NUMBER: _ClassVar[int]
    date: str
    inflow: float
    outflow: float
    missing: bool
    def __init__(self, date: _Optional[str] = ..., inflow: _Optional[float] = ..., outflow: _Optional[float] = ..., missing: _Optional[bool] = ...) -> None: ...

class ForecastRequest(_message.Message):
    __slots__ = ("model", "company_id", "industry", "history", "horizon_days", "n_paths", "seed")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    COMPANY_ID_FIELD_NUMBER: _ClassVar[int]
    INDUSTRY_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    HORIZON_DAYS_FIELD_NUMBER: _ClassVar[int]
    N_PATHS_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    model: str
    company_id: str
    industry: str
    history: _containers.RepeatedCompositeFieldContainer[DailyFlow]
    horizon_days: int
    n_paths: int
    seed: int
    def __init__(self, model: _Optional[str] = ..., company_id: _Optional[str] = ..., industry: _Optional[str] = ..., history: _Optional[_Iterable[_Union[DailyFlow, _Mapping]]] = ..., horizon_days: _Optional[int] = ..., n_paths: _Optional[int] = ..., seed: _Optional[int] = ...) -> None: ...

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
    __slots__ = ("model_used", "dates", "paths", "net_quantiles", "low_confidence")
    MODEL_USED_FIELD_NUMBER: _ClassVar[int]
    DATES_FIELD_NUMBER: _ClassVar[int]
    PATHS_FIELD_NUMBER: _ClassVar[int]
    NET_QUANTILES_FIELD_NUMBER: _ClassVar[int]
    LOW_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    model_used: str
    dates: _containers.RepeatedScalarFieldContainer[str]
    paths: _containers.RepeatedCompositeFieldContainer[Path]
    net_quantiles: _containers.RepeatedCompositeFieldContainer[NetQuantiles]
    low_confidence: bool
    def __init__(self, model_used: _Optional[str] = ..., dates: _Optional[_Iterable[str]] = ..., paths: _Optional[_Iterable[_Union[Path, _Mapping]]] = ..., net_quantiles: _Optional[_Iterable[_Union[NetQuantiles, _Mapping]]] = ..., low_confidence: _Optional[bool] = ...) -> None: ...

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
