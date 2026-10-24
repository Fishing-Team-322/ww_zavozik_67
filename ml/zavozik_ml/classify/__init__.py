"""Классификатор категорий банковских операций (закрытый список из 20 категорий).

    from zavozik_ml.classify import Classifier, Op
    clf = Classifier.load(DEFAULT_DIR)
    clf.predict([Op("out", "Оплата поставщику за товар", "ООО «Ромашка»", "0071234567", 1000.0)])
"""

from .model import DEFAULT_DIR, Classifier, Prediction
from .text import CATEGORIES, OTHER, Op

__all__ = ["CATEGORIES", "DEFAULT_DIR", "OTHER", "Classifier", "Op", "Prediction"]
