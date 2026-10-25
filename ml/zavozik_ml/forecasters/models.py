"""Импортирует все модели, чтобы они попали в реестр."""

from . import ensemble, ets, gbm, naive, structural  # noqa: F401
from . import event_models  # noqa: F401,E402 — registered serving wrappers
