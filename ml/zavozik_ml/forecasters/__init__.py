"""Прогнозные модели. Импорт модуля регистрирует модель в реестре."""

from . import naive  # noqa: F401
from .base import (
    Forecaster,
    History,
    InsufficientHistoryError,
    NotTrainedError,
    Paths,
    all_models,
    default_model,
    get,
    register,
)

__all__ = [
    "Forecaster",
    "History",
    "InsufficientHistoryError",
    "NotTrainedError",
    "Paths",
    "all_models",
    "default_model",
    "get",
    "register",
]
