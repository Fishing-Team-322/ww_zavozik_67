"""Прогнозные модели. Импорт модуля регистрирует модель в реестре."""

from . import naive  # noqa: F401
from .base import DEFAULT_MODEL, Forecaster, History, Paths, all_models, get, register

__all__ = ["DEFAULT_MODEL", "Forecaster", "History", "Paths", "all_models", "get", "register"]
